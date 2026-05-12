#!/bin/bash
# LLM Layout Generator V3 - Quick Run Script
# 适配新的 protocol 格式和 assets_annotated.json

# 默认参数
DEFAULT_PROTOCOL="DATA/protocols_batchv2/protocol_Alkylation_of_Ethyl_Acetoaceta_20251214_204328.json"
DEFAULT_OUTPUT="OUTPUT/llm_layouts_v3"
DEFAULT_MODEL="claude-sonnet-4-5-20250929"

# 从命令行参数获取（或使用默认值）
PROTOCOL="${1:-$DEFAULT_PROTOCOL}"
OUTPUT="${2:-$DEFAULT_OUTPUT}"
MODEL="${3:-$DEFAULT_MODEL}"

# 打印信息
echo "========================================"
echo "LLM Layout Generator V3"
echo "========================================"
echo "Protocol: $PROTOCOL"
echo "Output: $OUTPUT"
echo "Model: $MODEL"
echo "Asset Library: assets_annotated.json"
echo "========================================"

# 运行生成器
conda run -n holodeck python llm_layout_generator/generate_layout_v3.py \
    --protocol "$PROTOCOL" \
    --output "$OUTPUT" \
    --asset-library "assets_annotated.json" \
    --model "$MODEL" \
    --temperature 0.3

# 检查退出状态
if [ $? -eq 0 ]; then
    echo ""
    echo "========================================"
    echo "✓ Layout generation completed!"
    echo "========================================"
    echo "Next steps:"
    echo "1. Check the output in: $OUTPUT"
    echo "2. Convert to USD: cd . && bash usd.sh <output_file>"
    echo "3. Render in Isaac Sim"
else
    echo ""
    echo "========================================"
    echo "✗ Layout generation failed"
    echo "========================================"
    exit 1
fi
