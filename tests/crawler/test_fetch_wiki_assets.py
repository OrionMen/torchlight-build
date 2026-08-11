import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from crawler.fetch_wiki_assets import ASSET_USER_AGENT, TLIDB_REFERER, fetch_manifest, main, request_headers


def asset(name, kind="image", ext=".png"):
    asset_id=(name.encode().hex()*64)[:64]
    return {"asset_id":asset_id,"source_url":f"https://cdn.tlidb.com/{name}{ext}","asset_type":kind,
            "extension":ext,"local_relative_path":f"{kind}/{asset_id[:2]}/{asset_id[2:4]}/{asset_id}{ext}"}


def response(body=b"ok",status=200,retry_after=None,content_type="image/png"):
    return {"body":body,"http_status":status,"content_type":content_type,"etag":None,"last_modified":None,"retry_after":retry_after}


class WikiAssetFetchTest(unittest.TestCase):
    def write_manifest(self, root, assets):
        path=root/"asset-manifest.json"; path.write_text(json.dumps({"season":"ss13","assets":assets}),encoding="utf-8"); return path

    def test_tlidb_request_headers_do_not_leak_referer_to_third_party(self):
        for url in ("https://cdn.tlidb.com/a.webp", "https://tlidb.com/a.css", "https://www.tlidb.com/a.js"):
            with self.subTest(url=url):
                headers=request_headers(url)
                self.assertEqual(headers["User-Agent"],ASSET_USER_AGENT)
                self.assertEqual(headers["Referer"],TLIDB_REFERER)
        external=request_headers("https://example.com/library.js")
        self.assertEqual(external["User-Agent"],ASSET_USER_AGENT)
        self.assertNotIn("Referer",external)

    def test_success_cache_force_stale_part_and_atomic_rename(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); item=asset("one"); manifest=self.write_manifest(root,[item]); output=root/"files"
            final=output/item["local_relative_path"]; final.parent.mkdir(parents=True); part=final.with_suffix(final.suffix+".part"); part.write_bytes(b"partial")
            calls=[]
            def fetcher(url,timeout): calls.append(url); return response(b"complete")
            first=fetch_manifest(manifest,output,max_workers=1,rate_limit=0,retry=0,quiet=True,fetcher=fetcher)
            self.assertEqual(first["downloaded"],1); self.assertEqual(final.read_bytes(),b"complete"); self.assertFalse(part.exists())
            cached=fetch_manifest(manifest,output,max_workers=1,rate_limit=0,retry=0,quiet=True,fetcher=lambda *_: self.fail("HTTP used on cache"))
            self.assertEqual(cached["cache_hit"],1)
            forced=fetch_manifest(manifest,output,force=True,max_workers=1,rate_limit=0,retry=0,quiet=True,fetcher=fetcher)
            self.assertEqual(forced["downloaded"],1); self.assertEqual(len(calls),2)

    def test_retry_429_404_and_failure_continue(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); items=[asset("timeout"),asset("missing"),asset("limited")]; manifest=self.write_manifest(root,items)
            calls={"timeout":0,"missing":0,"limited":0}; sleeps=[]
            def fetcher(url,timeout):
                key=next(k for k in calls if k in url); calls[key]+=1
                if key=="timeout" and calls[key]==1: raise TimeoutError("timeout")
                if key=="missing": return response(status=404)
                if key=="limited" and calls[key]==1: return response(status=429,retry_after="2")
                return response(key.encode())
            report=fetch_manifest(manifest,root/"files",max_workers=1,rate_limit=0,retry=2,quiet=True,fetcher=fetcher,sleep=sleeps.append)
            self.assertEqual((report["downloaded"],report["failed"],report["retry_count"]),(2,1,2))
            self.assertEqual(calls["missing"],1); self.assertIn(2.0,sleeps); self.assertEqual(len(report["failed_assets"]),1)

    def test_ctrl_c_preserves_existing_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); manifest=self.write_manifest(root,[]); cached=root/"keep.bin"; cached.write_bytes(b"keep")
            output=io.StringIO()
            with patch("crawler.fetch_wiki_assets.fetch_manifest",side_effect=KeyboardInterrupt),redirect_stdout(output):
                code=main(["--manifest",str(manifest),"--output-root",str(root/"files")])
            self.assertEqual(code,130); self.assertEqual(cached.read_bytes(),b"keep"); self.assertIn("remain cached",output.getvalue())


if __name__ == "__main__": unittest.main()
