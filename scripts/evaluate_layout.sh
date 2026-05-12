#!/bin/bash
# 布局评估脚本

# 获取脚本所在目录（Table/Lablayout目录）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 设置默认路径（相对于脚本目录）
ASSET_DB="$SCRIPT_DIR/assets_annotated.json"
IMAGES_DIR="$SCRIPT_DIR/rendering_tools/final_5_views"

# 检查参数
if [ "$#" -lt 3 ]; then
    echo "使用方法: $0 <layout.json> <protocol.json> <output_dir>"
    echo "示例: $0 OUTPUT/layout.json DATA/protocols/protocol.json OUTPUT/evaluation/"
    exit 1
fi

LAYOUT_PATH=$1
PROTOCOL_PATH=$2
OUTPUT_DIR=$3

# 检查可选参数
SKIP_SEMANTIC=""
for arg in "$@"; do
    if [ "$arg" == "--skip-semantic" ]; then
        SKIP_SEMANTIC="--skip-semantic"
    fi
done

# 运行评估（切换到脚本目录）
cd "$SCRIPT_DIR"

python -m evaluator.main \
    --layout "$LAYOUT_PATH" \
    --protocol "$PROTOCOL_PATH" \
    --asset-db "$ASSET_DB" \
    --images-dir "$IMAGES_DIR" \
    --output "$OUTPUT_DIR" \
    $SKIP_SEMANTIC

echo ""
echo "评估完成！"
echo "查看报告：$OUTPUT_DIR"

