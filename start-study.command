#!/bin/zsh

# Double-click this file on macOS to open the local student study route.
# An existing course workspace can be passed as the first argument.
set -e

STUDY_ROOT="$(cd "$(dirname "$0")" && pwd)"
STUDY_PROJECT="${1:-$STUDY_ROOT/local-data/my-study}"
STUDY_PYTHON="$STUDY_ROOT/.venv/bin/python"
if [[ ! -x "$STUDY_PYTHON" ]]; then
  STUDY_PYTHON="$(command -v python3 || true)"
fi
if [[ -z "$STUDY_PYTHON" ]] || ! "$STUDY_PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
  echo "需要 Python 3.10 或更新版本。请先从 https://www.python.org/downloads/ 安装 Python，再双击打开。"
  read -k 1 "?按任意键关闭"
  exit 1
fi
cd "$STUDY_ROOT"
echo "正在打开自学讲义。请在网页中选择课程材料；已有讲义不会重新生成。"
PYTHONPATH="$STUDY_ROOT/src" "$STUDY_PYTHON" -m mst.cli serve "$STUDY_PROJECT" --port 0 --open
