#!/usr/bin/env python3
"""
LLM Layout Generator V3 - Main Script
适配新的 protocol 格式（DATA/protocols_batchv2/）和 assets_annotated.json

新特性：
1. Protocol 中每个资产都有明确的 initial_location
2. 使用 assets_annotated.json 作为资产库
3. LLM 只对 initial_location="floor" 的资产进行二次选择
4. 支持新的朝向系统（front_direction）
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from labgen.layout_generator.layout_engine_v3 import LLMLayoutEngineV3

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description='Generate laboratory layout using LLM (V3 - New protocol format)'
    )
    parser.add_argument(
        '--protocol',
        type=str,
        required=True,
        help='Path to protocol JSON file (from DATA/protocols_batchv2/)'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='OUTPUT/llm_layouts_v3',
        help='Output directory (default: OUTPUT/llm_layouts_v3)'
    )
    parser.add_argument(
        '--asset-library',
        type=str,
        default='assets_annotated.json',
        help='Path to assets_annotated.json (default: assets_annotated.json in Lablayout directory)'
    )
    parser.add_argument(
        '--model',
        type=str,
        default='claude-sonnet-4-5-20250929',
        help='LLM model to use (default: claude-sonnet-4-5-20250929)'
    )
    parser.add_argument(
        '--temperature',
        type=float,
        default=0.3,
        help='LLM temperature (default: 0.3)'
    )
    
    args = parser.parse_args()
    
    # 加载 protocol
    logger.info(f"Loading protocol from: {args.protocol}")
    with open(args.protocol, 'r', encoding='utf-8') as f:
        protocol = json.load(f)
    
    experiment_name = protocol.get('experiment_name', 'Unknown')
    logger.info(f"Experiment: {experiment_name}")
    logger.info(f"Assets: {len(protocol.get('assets', []))} items")
    
    # 统计资产的 initial_location
    locations = {}
    for asset in protocol.get('assets', []):
        loc = asset.get('initial_location', 'unknown')
        locations[loc] = locations.get(loc, 0) + 1
    logger.info(f"Asset locations: {locations}")
    
    # 初始化布局引擎
    logger.info(f"Initializing LLM Layout Engine V3 with model: {args.model}")
    
    llm_config = {
        "model": args.model,
        "temperature": args.temperature,
        "max_tokens": 8192
    }
    
    # 构建资产库路径（如果是相对路径，在 Lablayout 目录下）
    asset_library_path = args.asset_library
    if not Path(asset_library_path).is_absolute():
        # 假设脚本在 Lablayout/llm_layout_generator/ 目录
        lablayout_dir = Path(__file__).parent.parent
        asset_library_path = lablayout_dir / asset_library_path
    
    logger.info(f"Using asset library: {asset_library_path}")
    
    # 检查资产库文件是否存在
    if not Path(asset_library_path).exists():
        logger.error(f"Asset library file not found: {asset_library_path}")
        sys.exit(1)
    
    logger.info("Initializing LLM Layout Engine V3...")
    try:
        engine = LLMLayoutEngineV3(
            asset_library_path=str(asset_library_path),
            llm_config=llm_config
        )
        logger.info("LLM Layout Engine V3 initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize LLM Layout Engine: {e}", exc_info=True)
        sys.exit(1)
    
    # 生成布局
    logger.info("Starting layout generation...")
    try:
        output_path, layout_data = engine.generate_layout(
            protocol=protocol,
            output_dir=args.output
        )
        
        logger.info("="*60)
        logger.info("✓ Layout generation completed successfully!")
        logger.info(f"✓ Output file: {output_path}")
        logger.info(f"✓ Total objects: {len(layout_data['objects'])}")
        logger.info("="*60)
        
        # 打印统计信息
        room_count = sum(1 for obj in layout_data['objects'] if obj['initial_location'] == 'floor')
        desktop_count = sum(1 for obj in layout_data['objects'] if obj['initial_location'] != 'floor')
        
        logger.info(f"Room assets: {room_count}")
        logger.info(f"Desktop objects: {desktop_count}")
        
        # 打印输出文件路径
        print(f"\n✓ Isaac Sim layout saved to: {output_path}")
        print(f"  You can now convert it to USD using:")
        print(f"  cd .")
        print(f"  bash usd.sh {output_path}")
        
    except Exception as e:
        logger.error(f"✗ Layout generation failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
