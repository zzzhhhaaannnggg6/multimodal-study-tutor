"""Exercise the BUILT native WKWebView and frozen backend with synthetic input.

No browser driver, model service, user's workspace, system Python subprocess,
or accessibility permission is used by the app. Run in a logged-in macOS GUI.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import plistlib
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


def pdf_fixture() -> bytes:
    text = b"BT /F1 16 Tf 50 700 Td (Synthetic PDF evidence) Tj ET"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               b"<< /Length " + str(len(text)).encode() + b" >>\nstream\n" + text + b"\nendstream"]
    data = b"%PDF-1.4\n"
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data)); data += str(number).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    start = len(data)
    data += b"xref\n0 6\n0000000000 65535 f \n"
    data += b"".join(f"{offset:010} 00000 n \n".encode() for offset in offsets[1:])
    return data + f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()


SETUP = """
const assert = (condition, message) => { if(!condition) throw new Error(message); };
const wait = async (predicate) => { for(let i=0;i<600;i++) { if(await predicate()) return; await new Promise(r=>setTimeout(r,100)); } throw new Error('condition timed out'); };
const $ = (id) => document.getElementById(id);
assert($('generationMode').value === 'none', 'must default to local');
assert($('modelApiKey').value === '', 'must not restore credentials');
"""

FIRST = """
assert(!document.querySelector('#routeCards .unit-card'), 'new isolated workspace should be empty');
const files = new DataTransfer();
files.items.add(new File(['# 二进制转十进制\\n将二进制 (1101)2 转换为十进制，按位权展开计算。'], '合成课程.md', {type:'text/markdown'}));
files.items.add(new File([Uint8Array.from(atob(PDF_BYTES), c=>c.charCodeAt(0))], '合成页面.pdf', {type:'application/pdf'}));
$('sourceFiles').files=files.files;
$('sourceFiles').dispatchEvent(new Event('change', {bubbles:true}));
$('subject').value='computer-systems';
$('generateButton').click();
await wait(()=> document.querySelector('#routeCards .unit-card') && $('uploadMessage').textContent.includes('草稿已生成'));
const job=(await(await fetch('api/jobs/latest')).json()).job;
assert(job.status==='succeeded', 'generation did not succeed');
assert(job.materials.length===2, 'missing per-file receipts');
assert(job.materials.find(x=>x.name.endsWith('.pdf')).status !== 'unreadable', 'PDF must work without system pdftotext');
const guide=await(await fetch('study-guide.json')).json();
const numeric=guide.units[0];
assert(numeric.worked_examples[0].complete && numeric.worked_examples[0].answer.includes('(13)₁₀'), 'flattened base must produce the original concrete worked answer');
assert(numeric.practice_items.find(x=>x.kind==='transfer').answer.includes('(14)₁₀'), 'numeric variant must be solved, not an outline');
assert(guide.source_index.some(x=>(x.quote||'').includes('Synthetic PDF evidence')), 'bundled pypdf did not extract actual PDF text');
const pdfReceipt=job.materials.find(x=>x.name.endsWith('.pdf'));
assert(pdfReceipt.rendered_page_count===1, 'bundled PDF renderer did not produce the page');
document.querySelector('#routeCards [data-unit="1"]').click();
assert(guide.units[1].content_mode==='material-only', 'unknown PDF topic must stay material-only');
assert(document.querySelector('#lessonContent .content-gap'), 'missing explanation gap must be visible');
assert(!document.querySelector('#lessonContent .practice, #lessonContent .example, #markUnit'), 'material-only view must not contain mock teaching or completion');
const pageImage=document.querySelector('#lessonContent [data-material-image]');
assert(pageImage, 'source page missing beside explanation');
pageImage.scrollIntoView();
await wait(()=>pageImage.complete && pageImage.naturalWidth>0);
assert(pageImage.naturalWidth>500, 'PDF preview is not a full page');
for(const format of ['html','md','json']) {
  const response=await fetch('api/exports/'+format);
  const content=await response.text();
  assert(response.ok && content.length>100, 'export '+format);
  if(format==='html') assert(content.includes('src="data:image/png;base64,'), 'HTML must carry its source page offline');
}
for(const count of [1,2]) {
  document.querySelector('a[data-export="md"]').click();
  await wait(()=>window.__mstNativeDownloads===count);
}
$('startLearning').click();
const answer=document.querySelector('#lessonContent textarea');
assert(answer, 'no student practice');
answer.value='退出前刚写的答案 x²\\naddi x5, x0, 10';
answer.dispatchEvent(new Event('input', {bubbles:true}));
$('markUnit').click();
const closing=await window.StudyDesktop.prepareToClose();
assert(closing.saved && !closing.busy, 'close did not flush the newest answer');
return {passed:true, job_id:job.job_id, title:guide.title, units:guide.units.length, rendered_pdf_pages:pdfReceipt.rendered_page_count, inline_page_preview:true, exports:['html','md','json'], native_downloads:2, answer_saved:true};
"""

SECOND = """
assert($('learnView').hidden===false, 'reading view not restored');
const answer=document.querySelector('#lessonContent textarea');
assert(answer?.value==='退出前刚写的答案 x²\\naddi x5, x0, 10', 'last answer not restored');
assert($('progressText').textContent.startsWith('1/'), 'completion not restored');
assert(!document.querySelector('#lessonContent .practice details[open]'), 'answers should stay folded');
const job=(await(await fetch('api/jobs/latest')).json()).job;
assert(job.job_id===OLD_JOB, 'restart must not regenerate');
return {passed:true, job_id:job.job_id, restored:true};
"""


def run_check(app: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise SystemExit("Choose an empty --output directory; previous checks are preserved.")
    workspace = output / "synthetic-workspace"
    downloads = output / "synthetic-downloads"
    downloads.mkdir()
    environment = {key: value for key, value in os.environ.items() if not key.startswith(("PYTHON", "DYLD_"))}
    environment["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    backend = app / "Contents/Resources/backend/study-backend"
    runtime = json.loads(subprocess.check_output([str(backend), "--runtime-check"], env=environment, cwd="/tmp", timeout=15))
    assert runtime["frozen"] and runtime["tls_roots"] > 50 and runtime["tls_verify"] and runtime["tls_hostname_check"], runtime
    results = []
    # Move to a different path for the second launch, modelling replacement of
    # the application while retaining a stable workspace outside its bundle.
    with tempfile.TemporaryDirectory(prefix="mst-installed-preview-") as isolated:
        for index, body in enumerate((FIRST, SECOND), 1):
            launched_app = app
            if index == 2:
                launched_app = Path(isolated) / "Moved Preview.app"
                shutil.copytree(app, launched_app, symlinks=True)
            report = output / f"launch-{index}.json"
            script = output / f"launch-{index}.js"
            source = SETUP + body.replace("PDF_BYTES", json.dumps(base64.b64encode(pdf_fixture()).decode()))
            source = source.replace("OLD_JOB", json.dumps(results[0]["job_id"]) if results else "null")
            script.write_text(source, encoding="utf-8")
            child = subprocess.Popen([str(launched_app / "Contents/MacOS/StudyTutor"), "--workspace", str(workspace),
                         "--check-script", str(script), "--check-report", str(report),
                         "--check-download-dir", str(downloads),
                         "--check-snapshot", str(output / f"launch-{index}.png")], cwd="/tmp", env=environment,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                status = child.wait(90)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait(5)
                raise AssertionError("native app check timed out") from None
            result = json.loads(report.read_text()) if report.exists() else {"error": "native app produced no report"}
            assert status == 0 and result.get("passed"), result
            for _ in range(30):
                try:
                    os.kill(result["backend_pid"], 0)
                except ProcessLookupError:
                    break
                time.sleep(0.1)
            else:
                raise AssertionError("backend orphaned after native app quit")
            assert (output / f"launch-{index}.png").stat().st_size > 1000
            results.append(result)
    assert "二进制" in (downloads / "study-guide.md").read_text(encoding="utf-8")
    assert not list(downloads.glob(".mst-download-*.partial")), "unfinished native download files"
    with (app / "Contents/Info.plist").open("rb") as handle:
        metadata = plistlib.load(handle)
    summary = {"passed": True, "launches": results, "runtime": runtime, "minimum_macos": metadata["LSMinimumSystemVersion"],
               "system_python_used_by_app": False, "live_model_calls": 0,
               "manual_checks_remaining": ["native file picker", "native download save panel", "Gatekeeper on a downloaded archive", "other macOS versions and architectures"]}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run_check(args.app.resolve(), args.output.resolve())
