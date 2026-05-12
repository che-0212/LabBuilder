#!/usr/bin/env python3
"""
Experiment Protocol Planner - Main Entry Point

Usage:
    python run_planner.py "experiment description"
    
Example:
    python run_planner.py "酸碱滴定实验"
    python run_planner.py "H₂O₂ decomposition and catalytic effect"
"""

import os
import sys
import argparse
from labforge import ProtocolPlanner
from utils.llm_config import LLMConfig


def main():
    parser = argparse.ArgumentParser(
        description='Generate experiment protocols from natural language descriptions',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_planner.py "酸碱滴定实验"
  python run_planner.py "H₂O₂ decomposition with MnO₂ catalyst"
  python run_planner.py "Prepare sodium chloride solution" --temperature 0.5
  python run_planner.py "Distillation of ethanol-water mixture" --output-dir my_protocols
        """
    )
    
    parser.add_argument(
        'experiment',
        type=str,
        help='Natural language description of the experiment'
    )
    
    parser.add_argument(
        '--asset-library',
        type=str,
        default='assets_annotated.json',
        help='Path to asset library JSON file (default: assets_annotated.json)'
    )
    
    parser.add_argument(
        '--asset-captions',
        type=str,
        default=None,
        help='Path to asset captions JSON file (default: auto-detect from asset library directory)'
    )
    
    parser.add_argument(
        '--output-dir',
        type=str,
        default='DATA/protocols',
        help='Output directory for protocols (default: DATA/protocols)'
    )
    
    parser.add_argument(
        '--api-key',
        type=str,
        default=None,
        help='OpenAI API key (or set OPENAI_API_KEY env variable)'
    )
    
    parser.add_argument(
        '--base-url',
        type=str,
        default=None,
        help='API base URL (optional, for custom endpoints)'
    )
    
    parser.add_argument(
        '--model',
        type=str,
        default=None,
        help='Model name (default: from LLMConfig - gemini-3-pro-preview-thinking)'
    )
    
    parser.add_argument(
        '--temperature',
        type=float,
        default=None,
        help='Temperature for LLM (default: from LLMConfig - 0.3)'
    )
    
    parser.add_argument(
        '--max-tokens',
        type=int,
        default=None,
        help='Maximum tokens for response (default: from LLMConfig - 16000)'
    )
    
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Suppress progress output'
    )
    
    parser.add_argument(
        '--print-json',
        action='store_true',
        help='Print the generated protocol JSON'
    )
    
    parser.add_argument(
        '--no-strict-validation',
        action='store_true',
        help='Disable strict asset validation (allow unknown assets with warnings)'
    )
    
    parser.add_argument(
        '--max-retries',
        type=int,
        default=3,
        help='Maximum retry attempts for invalid protocols (default: 3)'
    )
    
    parser.add_argument(
        '--ragflow-api-key',
        type=str,
        default=None,
        help='RAGflow API key (or set RAGFLOW_API_KEY env variable). Required for RAG retrieval.'
    )
    
    parser.add_argument(
        '--ragflow-base-url',
        type=str,
        default='http://localhost:9380',
        help='RAGflow service base URL (default: http://localhost:9380)'
    )
    
    parser.add_argument(
        '--disable-rag',
        action='store_true',
        help='Disable RAG retrieval from knowledge base'
    )
    
    parser.add_argument(
        '--save-rag-results',
        action='store_true',
        help='Save RAG retrieval results to file for verification'
    )
    
    args = parser.parse_args()
    
    # Get API key (let LLMConfig handle defaults if not provided)
    api_key = args.api_key or os.environ.get('OPENAI_API_KEY') or None
    
    # Get RAGflow API key
    ragflow_api_key = args.ragflow_api_key or os.environ.get('RAGFLOW_API_KEY') or None
    
    # Check if asset library exists
    if not os.path.exists(args.asset_library):
        print(f"Error: Asset library not found: {args.asset_library}")
        sys.exit(1)
    
    try:
        # Initialize LLM config (only override if specified)
        llm_config = LLMConfig(
            api_key=api_key,
            base_url=args.base_url
        )
        # Override config if command-line args provided
        if args.model is not None:
            llm_config.model = args.model
        if args.temperature is not None:
            llm_config.temperature = args.temperature
        if args.max_tokens is not None:
            llm_config.max_tokens = args.max_tokens
        
        # Initialize planner with RAGflow support
        planner = ProtocolPlanner(
            asset_library_path=args.asset_library,
            llm_config=llm_config,
            asset_captions_path=args.asset_captions,
            ragflow_api_key=ragflow_api_key,
            ragflow_base_url=args.ragflow_base_url,
            enable_rag=not args.disable_rag
        )
        
        # Generate protocol
        protocol = planner.plan(
            experiment_description=args.experiment,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            verbose=not args.quiet,
            strict_validation=not args.no_strict_validation,
            max_retries=args.max_retries,
            save_rag_results=args.save_rag_results
        )
        
        filepath = planner.save_protocol(protocol, output_dir=args.output_dir)
        
        # Print JSON if requested
        if args.print_json:
            print("\nGenerated Protocol JSON:")
            print("=" * 60)
            print(protocol.to_json())
            print("=" * 60)
        
        # Print summary
        if not args.quiet:
            print("\n" + "=" * 60)
            print("PROTOCOL SUMMARY")
            print("=" * 60)
            print(f"\nExperiment: {protocol.experiment_name}")
            print(f"Description: {protocol.experiment_description}\n")
            
            print(f"Required Assets ({len(protocol.assets)}):")
            for asset in protocol.assets:
                print(f"  - {asset.name} ({asset.type}) x{asset.quantity}")
                if asset.purpose:
                    print(f"    Purpose: {asset.purpose}")
                if hasattr(asset, 'initial_location') and asset.initial_location:
                    print(f"    Initial Location: {asset.initial_location}")
            
            print(f"\nPhysical Constraints ({len(protocol.physical_constraints)}):")
            for constraint in protocol.physical_constraints:
                print(f"  - Type: {constraint.constraint_type}")
            
            print(f"\nChemical Constraints ({len(protocol.chemical_constraints)}):")
            for constraint in protocol.chemical_constraints:
                assets_info = []
                if constraint.asset1:
                    assets_info.append(constraint.asset1)
                if constraint.asset2:
                    assets_info.append(constraint.asset2)
                assets_str = " ↔ ".join(assets_info) if assets_info else "N/A"
                
                print(f"  - [{constraint.constraint_type}] {assets_str}")
                print(f"    {constraint.description}")
                if constraint.zone:
                    print(f"    Zone: {constraint.zone}")
                if constraint.storage_container:
                    print(f"    Storage: {constraint.storage_container}")
            
            print(f"\nProcedure ({len(protocol.procedure)} steps):")
            for step in protocol.procedure:
                print(f"  {step.step_number}. {step.description}")
                if hasattr(step, 'location') and step.location:
                    print(f"     Location: {step.location}")
                if step.safety_notes:
                    print(f"     Safety: {step.safety_notes}")
            
            if protocol.safety_warnings:
                print(f"\nSafety Warnings:")
                for warning in protocol.safety_warnings:
                    print(f"  ⚠ {warning}")
            
            print("\n" + "=" * 60)
        
        return 0
        
    except Exception as e:
        print(f"\nError: {str(e)}", file=sys.stderr)
        if not args.quiet:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())

