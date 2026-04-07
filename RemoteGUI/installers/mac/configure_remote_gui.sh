#!/bin/bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
open -a TextEdit "$ROOT_DIR/config.json"
