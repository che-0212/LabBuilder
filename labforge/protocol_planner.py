"""
Protocol Planner

Main module for generating experiment protocols using LLM.
"""

import json
import os
from typing import Dict, Optional, List, Tuple
from datetime import datetime

from .protocol_schema import ExperimentProtocol
from .protocol_prompt import ProtocolPromptGenerator
from .ragflow_client import RAGflowClient
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.llm_config import LLMConfig, ModelAPI


class ProtocolPlanner:
    """
    Protocol Planner that generates experiment protocols from natural language descriptions
    """
    
    def __init__(self, asset_library_path: str, llm_config: LLMConfig,
                 asset_captions_path: Optional[str] = None,
                 ragflow_api_key: Optional[str] = None,
                 ragflow_base_url: str = "http://localhost:9380",
                 enable_rag: bool = True):
        """
        Initialize the protocol planner
        
        Args:
            asset_library_path: Path to assets_annotated.json file (complete asset library)
            llm_config: LLM configuration
            asset_captions_path: Path to assets_annotated_captions.json file (for prompt generation)
                                If None, will try to find it in the same directory as asset_library_path
            ragflow_api_key: RAGflow API key (required if enable_rag=True)
            ragflow_base_url: RAGflow service base URL, default http://localhost:9380
            enable_rag: Whether to enable RAG retrieval, default True
        """
        self.asset_library_path = asset_library_path
        self.llm_config = llm_config
        self.model_api = ModelAPI(llm_config)
        self.enable_rag = enable_rag
        
        # Load complete asset library
        with open(asset_library_path, 'r', encoding='utf-8') as f:
            self.asset_library = json.load(f)
        
        # Load asset captions (for prompt generation)
        if asset_captions_path is None:
            # Try to find captions file in the same directory
            base_dir = os.path.dirname(asset_library_path)
            asset_captions_path = os.path.join(base_dir, "assets_annotated_captions.json")
        
        self.asset_captions = None
        if os.path.exists(asset_captions_path):
            with open(asset_captions_path, 'r', encoding='utf-8') as f:
                captions_data = json.load(f)
                self.asset_captions = captions_data.get('captions', [])
            print(f"✓ Loaded asset captions from: {asset_captions_path}")
        else:
            print(f"⚠ Warning: Asset captions file not found: {asset_captions_path}")
            print("  Will use full asset library for prompts")
        
        # Create asset lookup dictionary for quick access
        self.asset_dict = {asset['name']: asset for asset in self.asset_library.get('assets', [])}
        
        # Initialize prompt generator
        self.prompt_generator = ProtocolPromptGenerator(
            asset_library=self.asset_library,
            asset_captions=self.asset_captions
        )
        
        # Initialize RAGflow client if enabled
        self.ragflow_client = None
        if enable_rag:
            if not ragflow_api_key:
                raise ValueError("RAGflow API key is required when enable_rag=True")
            try:
                self.ragflow_client = RAGflowClient(
                    api_key=ragflow_api_key,
                    base_url=ragflow_base_url
                )
                print(f"✓ RAGflow client initialized (base_url: {ragflow_base_url})")
            except Exception as e:
                print(f"⚠ Warning: Failed to initialize RAGflow client: {str(e)}")
                print("  Continuing without RAG retrieval...")
                self.enable_rag = False
                self.ragflow_client = None
        
        print(f"✓ Loaded asset library from: {asset_library_path}")
        print(f"✓ Found {len(self.asset_library.get('assets', []))} assets")
        print(f"✓ Using model: {llm_config.model}")
        print(f"✓ RAG retrieval: {'ENABLED' if self.enable_rag and self.ragflow_client else 'DISABLED'}")
    
    def plan(self, experiment_description: str, 
             temperature: Optional[float] = None,
             max_tokens: Optional[int] = None,
             verbose: bool = True,
             strict_validation: bool = True,
             max_retries: int = 3,
             save_rag_results: bool = False) -> ExperimentProtocol:
        """
        Generate an experiment protocol from a natural language description
        
        Args:
            experiment_description: Natural language description of the experiment
            temperature: LLM temperature (lower = more deterministic)
            max_tokens: Maximum tokens for response
            verbose: Whether to print progress information
            strict_validation: If True, reject protocols with invalid assets and retry
            max_retries: Maximum number of retry attempts for invalid protocols
            save_rag_results: If True, save RAG retrieval results to file for verification
            
        Returns:
            ExperimentProtocol object
        """
        if verbose:
            print(f"\n{'='*60}")
            print(f"EXPERIMENT PROTOCOL PLANNING")
            print(f"{'='*60}")
            print(f"Request: {experiment_description}")
            print(f"Strict Validation: {'ON' if strict_validation else 'OFF'}")
            print(f"Max Retries: {max_retries}")
            print(f"{'='*60}\n")
        
        # RAG retrieval (if enabled)
        rag_context = ""
        retrieved_chunks = []
        if self.enable_rag and self.ragflow_client:
            try:
                if verbose:
                    print("→ Retrieving relevant information from RAGflow knowledge base...")
                    print(f"  Query: {experiment_description}")
                    print(f"  Dataset: protocol")
                
                # Retrieve relevant chunks from protocol knowledge base
                chunks = self.ragflow_client.retrieve(
                    question=experiment_description,
                    dataset_name="protocol",
                    page_size=5,
                    similarity_threshold=0.2
                )
                
                if chunks:
                    retrieved_chunks = chunks
                    rag_context = self.ragflow_client.format_retrieved_context(chunks)
                    if verbose:
                        print(f"✓ Retrieved {len(chunks)} relevant chunks from knowledge base")
                        print("\n" + "="*60)
                        print("RAG检索结果详情:")
                        print("="*60)
                        for i, chunk in enumerate(chunks, 1):
                            print(f"\n[Chunk {i}]")
                            print(f"  相似度: {chunk.get('similarity', 'N/A'):.3f}" if chunk.get('similarity') else "  相似度: N/A")
                            print(f"  向量相似度: {chunk.get('vector_similarity', 'N/A'):.3f}" if chunk.get('vector_similarity') else "  向量相似度: N/A")
                            print(f"  关键词相似度: {chunk.get('term_similarity', 'N/A'):.3f}" if chunk.get('term_similarity') else "  关键词相似度: N/A")
                            print(f"  来源文档: {chunk.get('document_name', 'N/A')}")
                            content_preview = chunk.get('content', '')[:200] + "..." if len(chunk.get('content', '')) > 200 else chunk.get('content', '')
                            print(f"  内容预览: {content_preview}")
                        print("="*60)
                        print(f"\n✓ RAG检索内容已整合到prompt中\n")
                    
                    # 保存RAG检索结果（如果启用）
                    if save_rag_results:
                        self._save_rag_results(experiment_description, chunks, verbose)
                else:
                    if verbose:
                        print("⚠ No relevant chunks found in knowledge base")
                        print("  (可能原因: 相似度阈值过高或知识库中没有相关内容)\n")
            except Exception as e:
                if verbose:
                    print(f"⚠ RAG retrieval failed: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    print("  Continuing without RAG context...\n")
                rag_context = ""
        elif verbose and not self.enable_rag:
            print("ℹ RAG检索已禁用（使用 --disable-rag 或 enable_rag=False）\n")
        elif verbose and not self.ragflow_client:
            print("⚠ RAGflow客户端未初始化，跳过RAG检索\n")
        
        # Generate prompts
        system_prompt, user_prompt = self.prompt_generator.generate_full_prompt(
            experiment_description,
            rag_context=rag_context
        )
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                if verbose:
                    if attempt > 0:
                        print(f"\n→ Retry attempt {attempt + 1}/{max_retries}...")
                    else:
                        print("→ Generating protocol using LLM...")
                    print(f"  Temperature: {temperature}")
                    print(f"  Max tokens: {max_tokens}\n")
                
                # Call LLM
                response = self.model_api.call_with_system(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                
                if verbose:
                    print("✓ Received response from LLM\n")
                
                # Parse response
                protocol = self._parse_response(response, verbose=verbose)
                
                # Validate protocol (strict mode)
                self._validate_protocol(protocol, verbose=verbose, strict=strict_validation)
                
                # If we reach here, validation passed
                if verbose:
                    print(f"\n{'='*60}")
                    print(f"PROTOCOL GENERATION COMPLETE")
                    if attempt > 0:
                        print(f"(Succeeded after {attempt + 1} attempts)")
                    print(f"{'='*60}")
                    print(f"Experiment: {protocol.experiment_name}")
                    print(f"Assets required: {len(protocol.assets)}")
                    if protocol.llm_generated_constraints:
                        print(f"LLM-generated safety constraints: {len(protocol.llm_generated_constraints)}")
                    if protocol.chemical_constraints:
                        print(f"Standard chemical constraints: {len(protocol.chemical_constraints)}")
                    print(f"Physical constraints: {len(protocol.physical_constraints)}")
                    print(f"Procedure steps: {len(protocol.procedure)}")
                    print(f"{'='*60}\n")
                
                return protocol
                
            except ValueError as e:
                # Validation error - retry if we have attempts left
                last_error = e
                if verbose:
                    print(f"✗ Validation failed: {str(e)}")
                    if attempt < max_retries - 1:
                        print(f"  Retrying with fresh generation...")
                continue
                
            except Exception as e:
                # Other errors - don't retry
                raise Exception(f"Failed to generate protocol: {str(e)}")
        
        # All retries exhausted
        if verbose:
            print(f"\n✗ Failed to generate valid protocol after {max_retries} attempts")
        raise Exception(f"Failed to generate valid protocol after {max_retries} attempts. Last error: {str(last_error)}")
    
    def _parse_response(self, response: str, verbose: bool = True) -> ExperimentProtocol:
        """
        Parse LLM response into ExperimentProtocol
        
        Args:
            response: Raw response from LLM
            verbose: Whether to print debug info
            
        Returns:
            ExperimentProtocol object
        """
        if verbose:
            print("→ Parsing LLM response...")
        
        # Extract JSON from response (in case there's markdown formatting)
        json_str = response.strip()
        
        # Remove markdown code blocks if present
        if json_str.startswith('```'):
            lines = json_str.split('\n')
            json_str = '\n'.join(lines[1:-1] if lines[-1].strip() == '```' else lines[1:])
            json_str = json_str.replace('```json', '').replace('```', '').strip()
        
        try:
            protocol_dict = json.loads(json_str)
            protocol = ExperimentProtocol.from_dict(protocol_dict)
            
            # Assign initial_location from asset library's initial_location
            for asset_item in protocol.assets:
                if asset_item.name in self.asset_dict:
                    asset_info = self.asset_dict[asset_item.name]
                    initial_location = asset_info.get('initial_location')
                    if initial_location:
                        asset_item.initial_location = initial_location
                        if verbose:
                            print(f"  → Assigned {asset_item.name}.initial_location = {initial_location} from asset library")
                    else:
                        if verbose:
                            print(f"  ⚠ Warning: {asset_item.name} has no initial_location in asset library")
                else:
                    if verbose:
                        print(f"  ⚠ Warning: {asset_item.name} not found in asset library")
            
            if verbose:
                print("✓ Successfully parsed protocol\n")
            
            return protocol
            
        except json.JSONDecodeError as e:
            if verbose:
                print(f"✗ JSON parsing error: {str(e)}")
                print(f"Response preview: {response[:500]}...")
            raise Exception(f"Failed to parse JSON response: {str(e)}")
    
    def _validate_protocol(self, protocol: ExperimentProtocol, verbose: bool = True, strict: bool = True):
        """
        Validate the generated protocol against asset library
        
        Args:
            protocol: Generated protocol
            verbose: Whether to print validation info
            strict: If True, raise exception on invalid assets; if False, only warn
            
        Raises:
            ValueError: If strict=True and invalid assets are found
        """
        if verbose:
            print("→ Validating protocol...")
        
        # Default assets that don't need to be in the library (common reagents)
        DEFAULT_ASSETS = {'Water', 'DistilledWater', 'DeionizedWater'}
        
        available_assets = {asset['name'] for asset in self.asset_library.get('assets', [])}
        # Add default assets to available list
        available_assets.update(DEFAULT_ASSETS)
        
        used_assets = {asset.name for asset in protocol.assets}
        
        # Check if all assets exist
        invalid_assets = used_assets - available_assets
        if invalid_assets:
            error_msg = f"Invalid assets detected: {invalid_assets}. These assets do not exist in the library."
            if verbose:
                print(f"✗ {error_msg}")
            
            if strict:
                raise ValueError(error_msg)
            else:
                warning = f"Warning: Unknown assets used: {invalid_assets}"
                protocol.notes += f"\n{warning}"
        
        # Valid location values (7 locations for steps, assets can have additional locations like ReagentCabinet)
        VALID_STEP_LOCATIONS = {'FumeHood', 'ExperimentalPlatform', 'ValidationPlatform', 'GloveBox', 'ReagentCabinet', 'RotaryEvaporator', 'GravityChromatographyColumn'}
        VALID_ASSET_LOCATIONS = {'floor', 'ExperimentalPlatform', 'ValidationPlatform', 'FumeHood', 'GloveBox', 'ReagentCabinet'}
        
        # 规范化函数：统一使用PascalCase命名（与资产库一致）
        def normalize_location(loc: str) -> str:
            """将location名称规范化为标准的PascalCase格式"""
            mapping = {
                'ExperimentalPlatform': 'ExperimentalPlatform',
                'ValidationPlatform': 'ValidationPlatform',
                'experimental_platform': 'ExperimentalPlatform',
                'validation_platform': 'ValidationPlatform',
                'FumeHood': 'FumeHood',
                'GloveBox': 'GloveBox',
                'reagent_cabinet': 'ReagentCabinet',
                'ReagentCabinet': 'ReagentCabinet',
                'RotaryEvaporator': 'RotaryEvaporator',
                'GravityChromatographyColumn': 'GravityChromatographyColumn',
                'floor': 'floor'
            }
            return mapping.get(loc, loc)  # 如果不在映射中，返回原值
        
        # Validate location assignments for assets
        missing_location_assets = []
        invalid_location_assets = []
        for asset in protocol.assets:
            if not hasattr(asset, 'initial_location') or not asset.initial_location:
                missing_location_assets.append(asset.name)
            else:
                # 规范化location名称
                normalized_location = normalize_location(asset.initial_location)
                if normalized_location not in VALID_ASSET_LOCATIONS:
                    invalid_location_assets.append(f"{asset.name}: {asset.initial_location}")
                else:
                    # 更新为规范化后的值
                    asset.initial_location = normalized_location
        
        if missing_location_assets:
            error_msg = f"Assets missing initial_location: {missing_location_assets}"
            if verbose:
                print(f"✗ {error_msg}")
            if strict:
                raise ValueError(error_msg)
        
        if invalid_location_assets:
            error_msg = f"Assets with invalid initial_location (must be one of {VALID_ASSET_LOCATIONS}): {invalid_location_assets}"
            if verbose:
                print(f"✗ {error_msg}")
            if strict:
                raise ValueError(error_msg)
        
        # Validate location assignments for procedure steps
        missing_location_steps = []
        invalid_location_steps = []
        first_step_location = None
        for step in protocol.procedure:
            if not hasattr(step, 'location') or not step.location:
                missing_location_steps.append(f"Step {step.step_number}")
            else:
                # 规范化location名称
                normalized_location = normalize_location(step.location)
                if normalized_location not in VALID_STEP_LOCATIONS:
                    invalid_location_steps.append(f"Step {step.step_number}: {step.location}")
                else:
                    # 更新为规范化后的值
                    step.location = normalized_location
                    if step.step_number == 1:
                        first_step_location = normalized_location
        
        # Validate that first step is ReagentCabinet
        if first_step_location and first_step_location != 'ReagentCabinet':
            error_msg = f"First step must have location 'ReagentCabinet' (to retrieve reagents), but got '{first_step_location}'"
            if verbose:
                print(f"✗ {error_msg}")
            if strict:
                raise ValueError(error_msg)
        
        if missing_location_steps:
            error_msg = f"Steps missing location: {missing_location_steps}"
            if verbose:
                print(f"✗ {error_msg}")
            if strict:
                raise ValueError(error_msg)
        
        if invalid_location_steps:
            error_msg = f"Steps with invalid location (must be one of {VALID_STEP_LOCATIONS}): {invalid_location_steps}"
            if verbose:
                print(f"✗ {error_msg}")
            if strict:
                raise ValueError(error_msg)
        
        # Validate chemical constraints
        # Check LLM-generated constraints (new format - no predefined types)
        if protocol.llm_generated_constraints:
            for constraint in protocol.llm_generated_constraints:
                # For LLM-generated constraints, we don't validate constraint_type
                # (it's open-ended), only check that referenced assets exist
                if constraint.asset1 and constraint.asset1 not in available_assets:
                    if verbose:
                        print(f"✗ LLM constraint references unknown asset: {constraint.asset1}")
                    if strict:
                        raise ValueError(f"LLM constraint references unknown asset: {constraint.asset1}")
                if constraint.asset2 and constraint.asset2 not in available_assets:
                    if verbose:
                        print(f"✗ LLM constraint references unknown asset: {constraint.asset2}")
                    if strict:
                        raise ValueError(f"LLM constraint references unknown asset: {constraint.asset2}")
        
        # Validate standard chemical constraints (old format - must be C1-C10)
        if protocol.chemical_constraints:
            valid_chemical_constraint_types = {'C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'C7', 'C8', 'C9', 'C10'}
            for constraint in protocol.chemical_constraints:
                # Check constraint type is valid
                if constraint.constraint_type not in valid_chemical_constraint_types:
                    if verbose:
                        print(f"✗ Unknown chemical constraint type: {constraint.constraint_type}")
                    if strict:
                        raise ValueError(f"Unknown chemical constraint type: {constraint.constraint_type}")
                
                # Check assets exist
                if constraint.asset1 and constraint.asset1 not in available_assets:
                    if verbose:
                        print(f"✗ Chemical constraint references unknown asset: {constraint.asset1}")
                    if strict:
                        raise ValueError(f"Chemical constraint references unknown asset: {constraint.asset1}")
                if constraint.asset2 and constraint.asset2 not in available_assets:
                    if verbose:
                        print(f"✗ Chemical constraint references unknown asset: {constraint.asset2}")
                    if strict:
                        raise ValueError(f"Chemical constraint references unknown asset: {constraint.asset2}")
        
        # Validate physical constraints
        valid_physical_types = {'boundary', 'non_overlap'}
        for constraint in protocol.physical_constraints:
            if constraint.constraint_type not in valid_physical_types:
                if verbose:
                    print(f"✗ Unknown physical constraint type: {constraint.constraint_type}")
                if strict:
                    raise ValueError(f"Unknown physical constraint type: {constraint.constraint_type}")
        
        # Validate chemical constraint zones (if specified)
        all_constraints = protocol.llm_generated_constraints + protocol.chemical_constraints
        for constraint in all_constraints:
            if constraint.zone and constraint.zone not in VALID_ASSET_LOCATIONS:
                if verbose:
                    print(f"⚠ Warning: Chemical constraint has invalid zone: {constraint.zone}")
                if strict:
                    raise ValueError(f"Invalid zone in chemical constraint: {constraint.zone}")
            # Also check required_zone (new field for LLM constraints)
            if hasattr(constraint, 'required_zone') and constraint.required_zone and constraint.required_zone not in VALID_ASSET_LOCATIONS:
                if verbose:
                    print(f"⚠ Warning: Chemical constraint has invalid required_zone: {constraint.required_zone}")
                if strict:
                    raise ValueError(f"Invalid required_zone in chemical constraint: {constraint.required_zone}")
        
        if verbose:
            # Print location summary by location type
            location_counts_assets = {}
            location_counts_steps = {}
            for loc in VALID_ASSET_LOCATIONS:
                location_counts_assets[loc] = [a.name for a in protocol.assets if hasattr(a, 'initial_location') and a.initial_location == loc]
            for loc in VALID_STEP_LOCATIONS:
                location_counts_steps[loc] = [s.step_number for s in protocol.procedure if hasattr(s, 'location') and s.location == loc]
            
            print(f"✓ Location assignments validated:")
            print(f"  Assets by location:")
            for loc in VALID_ASSET_LOCATIONS:
                count = len(location_counts_assets[loc])
                if count > 0:
                    print(f"    - {loc}: {count} ({', '.join(location_counts_assets[loc][:5])}{'...' if count > 5 else ''})")
            print(f"  Steps by location:")
            for loc in VALID_STEP_LOCATIONS:
                count = len(location_counts_steps[loc])
                if count > 0:
                    print(f"    - {loc}: {count} steps {location_counts_steps[loc]}")
            print("✓ Validation complete\n")
    
    def save_protocol(self, protocol: ExperimentProtocol, 
                     output_dir: str = "DATA/protocols",
                     filename: Optional[str] = None) -> str:
        """
        Save protocol to file
        
        Args:
            protocol: Protocol to save
            output_dir: Output directory
            filename: Optional filename (auto-generated if not provided)
            
        Returns:
            Path to saved file
        """
        os.makedirs(output_dir, exist_ok=True)
        
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # 替换Windows文件系统的非法字符: < > : " / \ | ? *
            safe_name = protocol.experiment_name
            for char in ['<', '>', ':', '"', '/', '\\', '|', '?', '*']:
                safe_name = safe_name.replace(char, '_')
            safe_name = safe_name.replace(' ', '_')[:30]
            filename = f"protocol_{safe_name}_{timestamp}.json"
        
        filepath = os.path.join(output_dir, filename)
        protocol.save_to_file(filepath)
        
        print(f"✓ Protocol saved to: {filepath}")
        return filepath
    
    def plan_and_save(self, experiment_description: str,
                     output_dir: str = "DATA/protocols",
                     temperature: Optional[float] = None,
                     max_tokens: Optional[int] = None,
                     verbose: bool = True,
                     strict_validation: bool = True,
                     max_retries: int = 3) -> tuple[ExperimentProtocol, str]:
        """
        Generate protocol and save to file
        
        Args:
            experiment_description: Natural language description
            output_dir: Output directory
            temperature: LLM temperature
            max_tokens: Maximum tokens
            verbose: Whether to print progress
            strict_validation: If True, reject protocols with invalid assets and retry
            max_retries: Maximum number of retry attempts
            
        Returns:
            Tuple of (protocol, filepath)
        """
        protocol = self.plan(
            experiment_description=experiment_description,
            temperature=temperature,
            max_tokens=max_tokens,
            verbose=verbose,
            strict_validation=strict_validation,
            max_retries=max_retries
        )
        
        filepath = self.save_protocol(protocol, output_dir=output_dir)
        
        return protocol, filepath
    
    def _save_rag_results(self, query: str, chunks: List[dict], verbose: bool = True):
        """
        保存RAG检索结果到文件，用于验证
        
        Args:
            query: 检索查询
            chunks: 检索到的chunks
            verbose: 是否打印信息
        """
        try:
            os.makedirs("DATA/rag_results", exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_query = query.replace(' ', '_').replace('/', '_')[:50]
            filename = f"rag_results_{safe_query}_{timestamp}.json"
            filepath = os.path.join("DATA/rag_results", filename)
            
            result_data = {
                "query": query,
                "timestamp": timestamp,
                "chunks_count": len(chunks),
                "chunks": chunks
            }
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(result_data, f, indent=2, ensure_ascii=False)
            
            if verbose:
                print(f"✓ RAG检索结果已保存到: {filepath}")
        except Exception as e:
            if verbose:
                print(f"⚠ 保存RAG检索结果失败: {str(e)}")

