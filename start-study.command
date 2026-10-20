#!/bin/zsh

# Double-click this file on macOS to open the local student study route.
# A project folder can also be passed as the first argument.
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
SOURCE_DIR="${1:-}"

if [[ -z "$SOURCE_DIR" && "$(uname -s)" == "Darwin" ]]; then
  SOURCE_DIR="$(osascript -e 'POSIX path of (choose folder with prompt "选择课程材料所在文件夹")' 2>/dev/null || true)"
fi

if [[ -z "$SOURCE_DIR" ]]; then
  SOURCE_DIR="$ROOT/examples/minimal_course"
fi

cd "$ROOT"
if [[ -f "$SOURCE_DIR/project.json" ]]; then
  PROJECT="$SOURCE_DIR"
  PYTHONPATH="$ROOT/src" python3 -m mst.cli generate "$PROJECT"
else
  PROJECT="$SOURCE_DIR/.study-tutor"
  PYTHONPATH="$ROOT/src" python3 -m mst.cli quickstart "$PROJECT" "$SOURCE_DIR" --subject computer-systems
fi
echo "正在打开自学讲义：$PROJECT"
PYTHONPATH="$ROOT/src" python3 -m mst.cli serve "$PROJECT" --open
