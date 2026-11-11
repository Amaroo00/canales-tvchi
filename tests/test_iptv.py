import array
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import io

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import guardian
import iptv
import refresh_tokens
import sync_public_sources
from update_playlist import parse_m3u

CHANNEL = {"id": "Test.cl", "name": "Test", "group": "Nacionales",
           "page": "https://test.example.org/", "hosts": ["example.org"],
           "stream_keys": ["/test/"], "urls": ["https://cdn.example.org/test/main.m3u8"]}
URL = CHANNEL["urls"][0]
MEDIA = "#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6,\nsegment1.ts\n#EXTINF:6,\nsegment2.ts\n"


class SecurityTests(unittest.TestCase):
    def test_catalog_is_valid_and_all_seeds_are_allowed(self):
        catalog = iptv.load_catalog()
        self.assertEqual(len(catalog["channels"]), 42)
        for channel in catalog["channels"]:
            for url in channel["urls"]:
                self.assertTrue(iptv.allowed_url(channel, url), (channel["name"], url))

    def test_reject_unsafe_urls(self):
        for url in ("http://cdn.example.org/test/a.m3u8", "https://127.0.0.1/test/a",
                    "https://localhost/test/a", "file:///private", "https://user:pass@cdn.example.org/test/a",
                    "https://example.org.evil.com/test/a", "https://cdn.example.org/other/a",
                    "https://127.1/test/a", "https://0177.0.0.1/test/a",
                    URL + "\r\nCookie: secret", "https://[broken"):
            self.assertFalse(iptv.allowed_url(CHANNEL, url), url)

    def test_no_substring_host_matching(self):
        self.assertFalse(iptv.host_matches("evil-example.org", "example.org"))
        self.assertFalse(iptv.host_matches("example.org.evil.test", "example.org"))
        self.assertTrue(iptv.host_matches("cdn.example.org", "example.org"))

    def test_tokens_not_saved_as_backups(self):
        self.assertIsNone(iptv.stable_url(URL + "?access_token=secret"))
        self.assertIsNone(iptv.stable_url(URL + "?token=secret"))
        self.assertEqual(iptv.stable_url(URL + "?PlaylistM3UCL"), URL)

    def test_no_cross_channel_emergency_replacements(self):
        channels = {ch["id"]: ch for ch in iptv.load_catalog()["channels"]}
        agriculture = channels["AgriculturaTV.cl"]["urls"][0]
        self.assertFalse(iptv.allowed_url(channels["MeganoticiasAhora.cl"], agriculture))
        self.assertFalse(iptv.allowed_url(channels["24Horas.cl"], channels["TVN.cl"]["urls"][0]))

    def test_atomic_write_preserves_old_file_on_replace_error(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "canales.m3u"
            path.write_text("original", encoding="utf-8")
            with patch("iptv.os.replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    iptv.atomic_write(path, "new")
            self.assertEqual(path.read_text(), "original")
            self.assertFalse(path.with_name(path.name + ".tmp").exists())

    def test_ffmpeg_restricted_protocols_and_tls(self):
        args = iptv.ffmpeg_input(URL, {}, 8)
        self.assertIn("-tls_verify", args)
        self.assertNotIn("file", args[args.index("-protocol_whitelist") + 1])
        with self.assertRaises(iptv.StreamError):
            iptv.ffmpeg_input("file:///test", {}, 8)


class ManifestTests(unittest.TestCase):
    def fake_fetch(self, url, *args, **kwargs):
        if url.endswith(".ts"):
            return b"\x47" * 1024, url, {"Content-Type": "video/mp2t"}
        return MEDIA.encode(), url, {}

    @patch("iptv.fetch")
    def test_hls_segments_are_read(self, fetch):
        fetch.side_effect = self.fake_fetch
        result = iptv.inspect_hls(URL, {})
        self.assertEqual(result["video_url"], URL)
        self.assertGreaterEqual(fetch.call_count, 2)

    @patch("iptv.fetch", return_value=(b"<html>error</html>", URL, {}))
    def test_http_200_html_is_not_success(self, _):
        with self.assertRaisesRegex(iptv.StreamError, "manifiesto HLS"):
            iptv.inspect_hls(URL, {})

    @patch("iptv.fetch", return_value=(b"#EXTM3U\n", URL, {}))
    def test_empty_playlist_not_success(self, _):
        with self.assertRaisesRegex(iptv.StreamError, "no tiene segmentos"):
            iptv.inspect_hls(URL, {})

    @patch("iptv.fetch")
    def test_bad_segment_not_success(self, fetch):
        fetch.side_effect = [(MEDIA.encode(), URL, {}), (b"<html>error</html>", URL, {"Content-Type": "text/html"})]
        with self.assertRaisesRegex(iptv.StreamError, "Segmento"):
            iptv.inspect_hls(URL, {})

    @patch("iptv.fetch")
    def test_encryption_not_bypassed(self, fetch):
        fetch.return_value = ((MEDIA + '#EXT-X-KEY:METHOD=SAMPLE-AES,URI="key"\n').encode(), URL, {})
        with self.assertRaises(iptv.StreamError) as caught:
            iptv.inspect_hls(URL, {})
        self.assertEqual(caught.exception.state, "restricted")

    def test_variant_prefers_h264_and_moderate_bitrate(self):
        variants = [({"CODECS": "hvc1,mp4a.40.2", "BANDWIDTH": "2500000"}, "hevc"),
                    ({"CODECS": "avc1,mp4a.40.2", "BANDWIDTH": "9000000"}, "large"),
                    ({"CODECS": "avc1,mp4a.40.2", "BANDWIDTH": "2400000"}, "compatible")]
        self.assertEqual(sorted(variants, key=iptv.variant_rank)[0][1], "compatible")

    @patch("iptv.fetch")
    def test_master_follows_relative_video_and_external_spanish_audio(self, fetch):
        master = ('#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",LANGUAGE="en",URI="en.m3u8",DEFAULT=YES\n'
                  '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",LANGUAGE="es",URI="es.m3u8"\n'
                  '#EXT-X-STREAM-INF:BANDWIDTH=2400000,CODECS="avc1,mp4a.40.2",AUDIO="a"\nvideo.m3u8\n')
        def fake(url, *args, **kwargs):
            if url == URL:
                return master.encode(), url, {}
            return self.fake_fetch(url, *args, **kwargs)
        fetch.side_effect = fake
        result = iptv.inspect_hls(URL, {})
        self.assertEqual(result["video_url"], "https://cdn.example.org/test/video.m3u8")
        self.assertEqual(result["audio_url"], "https://cdn.example.org/test/es.m3u8")

    @patch("iptv.fetch")
    def test_http_403_is_never_online(self, fetch):
        fetch.side_effect = iptv.StreamError("unverified", "HTTP 403")
        self.assertEqual(iptv.verify_stream(CHANNEL, URL)["state"], "unverified")

    @patch("iptv.fetch")
    def test_manifest_only_never_marks_online(self, fetch):
        fetch.side_effect = self.fake_fetch
        result = iptv.verify_stream(CHANNEL, URL, manifest_only=True)
        self.assertEqual(result["state"], "unverified")


class AudioTests(unittest.TestCase):
    def pcm(self, values):
        data = array.array("h", values)
        if sys.byteorder != "little":
            data.byteswap()
        return data.tobytes()

    def test_silence_warning_not_false_success(self):
        result = iptv.audio_metrics(self.pcm([0] * 96000))
        self.assertTrue(result["warnings"])
        self.assertLess(result["rms_dbfs"], -60)

    def test_clipping_warning(self):
        result = iptv.audio_metrics(self.pcm([32767, -32768] * 48000))
        self.assertEqual(result["clipping_percent"], 100)
        self.assertTrue(result["warnings"])

    def test_normal_audio(self):
        self.assertFalse(iptv.audio_metrics(self.pcm([2000, -2000] * 48000))["warnings"])

    def test_missing_samples(self):
        with self.assertRaises(iptv.StreamError):
            iptv.audio_metrics(b"")

    @patch("iptv.decode_audio", return_value={"rms_dbfs": -20, "clipping_percent": 0, "warnings": []})
    @patch("iptv.probe_media")
    @patch("iptv.shutil.which", return_value="tool")
    @patch("iptv.inspect_hls", return_value={"video_url": URL, "audio_url": None})
    def test_audio_video_required(self, _, __, probe, decode):
        probe.return_value = [{"codec_type": "video", "codec_name": "h264", "nb_read_packets": "5"}]
        self.assertEqual(iptv.verify_stream(CHANNEL, URL)["state"], "offline")
        decode.assert_not_called()
        probe.return_value.append({"codec_type": "audio", "codec_name": "aac", "nb_read_packets": "10"})
        self.assertEqual(iptv.verify_stream(CHANNEL, URL)["state"], "online")


class SyncTests(unittest.TestCase):
    def test_country_suffix_and_decorations_are_normalized(self):
        self.assertEqual(iptv.name_key("Cooperativa ✪ | CL"), iptv.name_key("Cooperativa"))

    @patch("sync_public_sources.fetch")
    def test_official_page_discovery_still_requires_approved_route(self, fetch):
        fetch.return_value = ((f'<video src="{URL}"></video><video src="https://cdn.example.org/wrong/a.m3u8"></video>').encode(), URL, {})
        self.assertEqual(sync_public_sources.page_candidates(CHANNEL, 8), [(URL, "Página pública de la emisora")])

    def test_offline_sources_preserve_approved_backups(self):
        previous = {"channels": {CHANNEL["id"]: [{"url": URL, "source": "old"}]}}
        result = sync_public_sources.sync_sources({"channels": [CHANNEL]}, {"lists": []}, previous)
        self.assertEqual(len(result["channels"][CHANNEL["id"]]), 1)

    @patch("sync_public_sources.fetch")
    def test_external_list_does_not_add_channels_or_wrong_streams(self, fetch):
        text = ('#EXTM3U\n#EXTINF:-1,Test\nhttps://cdn.example.org/wrong/main.m3u8\n'
                '#EXTINF:-1,Other\nhttps://cdn.example.org/test/other.m3u8\n')
        fetch.return_value = (text.encode(), URL, {})
        bank = sync_public_sources.sync_sources({"channels": [CHANNEL]},
            {"lists": [{"name": "source", "url": URL}]}, log=lambda _: None)
        self.assertEqual(list(bank["channels"]), [CHANNEL["id"]])
        self.assertEqual([item["url"] for item in bank["channels"][CHANNEL["id"]]], [URL])

    @patch("sync_public_sources.fetch", side_effect=iptv.StreamError("offline", "HTTP 503"))
    def test_failed_source_is_warning_not_erasure(self, _):
        bank = sync_public_sources.sync_sources({"channels": [CHANNEL]},
            {"lists": [{"name": "source", "url": URL}]}, log=lambda _: None)
        self.assertTrue(bank["source_warnings"])
        self.assertEqual(bank["channels"][CHANNEL["id"]][0]["url"], URL)


class GuardianTests(unittest.TestCase):
    @patch("sys.argv", ["guardian.py", "--dry-run", "--offline", "--manifest-only"])
    @patch("sys.stdout", new_callable=io.StringIO)
    @patch("guardian.atomic_write")
    @patch("guardian.write_json")
    @patch("guardian.existing_urls", return_value={})
    @patch("guardian.load_catalog", return_value={"channels": [CHANNEL]})
    @patch("guardian.verify_stream", return_value={"state": "unverified", "detail": "HLS only"})
    @patch("guardian.load_json")
    def test_dry_run_never_writes_outputs(self, load, verify, catalog, previous, json_write, text_write, output):
        load.side_effect = [{"timeout": 8}, {"channels": {CHANNEL["id"]: [{"url": URL, "source": "seed"}]}}]
        self.assertEqual(guardian.main(), 0)
        json_write.assert_not_called()
        text_write.assert_not_called()

    @patch("guardian.verify_stream")
    def test_failover_and_only_verified_backups_count(self, verify):
        backup = "https://cdn.example.org/test/backup.m3u8"
        verify.side_effect = [{"state": "unverified", "detail": "HTTP 403"},
                              {"state": "online", "detail": "OK"}]
        _, url, result = guardian.check_channel(CHANNEL, [{"url": URL, "source": "A"}, {"url": backup, "source": "B"}])
        self.assertEqual(url, backup)
        self.assertEqual(result["state"], "online")
        self.assertEqual(result["verified_backups"], 0)

    @patch("guardian.verify_stream")
    def test_good_audio_preferred_over_warning(self, verify):
        backup = "https://cdn.example.org/test/backup.m3u8"
        verify.side_effect = [{"state": "warning", "detail": "silence"}, {"state": "online", "detail": "OK"}]
        self.assertEqual(guardian.check_channel(CHANNEL, [{"url": URL, "source": "A"}, {"url": backup, "source": "B"}])[1], backup)

    @patch("guardian.verify_stream", return_value={"state": "offline", "detail": "timeout"})
    def test_all_failed_keeps_previous_url(self, _):
        backup = "https://cdn.example.org/test/backup.m3u8"
        result = guardian.check_channel(CHANNEL, [{"url": URL, "source": "A"}], previous_url=backup)
        self.assertEqual(result[1], backup)
        self.assertEqual(result[2]["state"], "offline")

    def test_channel_without_authorized_source_stays_pending(self):
        result = guardian.check_channel(CHANNEL, [])
        self.assertIsNone(result[1])
        self.assertEqual(result[2]["state"], "pending")

    def test_one_url_per_m3u_entry(self):
        playlist = "#EXTM3U\n" + iptv.m3u_entry(CHANNEL, URL)
        entries = parse_m3u(playlist)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["urls"], [URL])
        self.assertIn('tvg-id="Test.cl"', playlist)

    def test_health_does_not_leak_tokens(self):
        result = guardian.public_attempt({"url": URL + "?access_token=secret", "source": "TVN"},
                                         {"state": "online", "detail": "OK", "preferred_url": URL + "?token=secret"})
        self.assertNotIn("secret", json.dumps(result))


class TVNTests(unittest.TestCase):
    @patch("refresh_tokens.fetch", side_effect=iptv.StreamError("unverified", "HTTP 403"))
    def test_tvn_403_does_not_generate_token(self, _):
        self.assertIsNone(refresh_tokens.resolve_tvn()[0])

    @patch("refresh_tokens.fetch")
    def test_tvn_only_uses_known_id_and_url_encodes_token(self, fetch):
        fetch.return_value = (b"id:'other', access_token:'wrong'", URL, {})
        self.assertIsNone(refresh_tokens.resolve_tvn()[0])
        html = f"id:'{refresh_tokens.MEDIA_ID}', access_token:'a&b'"
        fetch.return_value = (html.encode(), URL, {})
        self.assertTrue(refresh_tokens.resolve_tvn()[0].endswith("access_token=a%26b"))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Requiere las herramientas multimedia instaladas en Actions")
class MediaIntegrationTests(unittest.TestCase):
    def test_real_packets_and_audio_decoder_with_synthetic_fixture(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = str(Path(folder) / "sample.mp4")
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                            "color=c=black:s=160x90:r=10", "-f", "lavfi", "-i",
                            "sine=frequency=440:sample_rate=16000", "-t", "2", "-c:v", "mpeg4",
                            "-c:a", "aac", fixture], check=True, timeout=30)
            # Solo esta prueba usa un archivo local generado por nosotros, nunca datos externos.
            with patch("iptv.ffmpeg_input", return_value=["-i", fixture]):
                streams = iptv.probe_media(URL, {})
                self.assertEqual({item["codec_type"] for item in streams}, {"video", "audio"})
                self.assertTrue(all(int(item["nb_read_packets"]) > 0 for item in streams))
                metrics = iptv.decode_audio(URL, {})
                self.assertFalse(metrics["warnings"])
                self.assertGreater(metrics["rms_dbfs"], -60)


if __name__ == "__main__":
    unittest.main()
