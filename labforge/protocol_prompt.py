"""
Protocol Planning Prompt Generator

Generates prompts for LLM to create experiment protocols.
Focus on minimizing JSON comprehension effort and maximizing protocol design reasoning.
"""

import json
from typing import Dict, List, Optional


class ProtocolPromptGenerator:
    """Generate prompts for protocol planning"""
    
    def __init__(self, asset_library: Dict, asset_captions: Optional[List[Dict]] = None):
        """
        Initialize with asset library and captions
        
        Args:
            asset_library: The loaded assets_annotated.json dictionary (complete asset library)
            asset_captions: List of asset captions from assets_annotated_captions.json (for prompt generation)
        """
        self.asset_library = asset_library
        self.asset_captions = asset_captions or []
        
        # Create caption lookup dictionary
        self.caption_dict = {cap['id']: cap['caption'] for cap in self.asset_captions}
    
    def _get_simplified_asset_summary(self) -> str:
        """Generate a simplified asset summary using captions for initial selection"""
        assets = self.asset_library.get('assets', [])
        
        # Group by type
        instruments = [a for a in assets if a['type'] == 'instrument']
        reagents = [a for a in assets if a['type'] == 'reagent']
        
        # Build summary with captions
        summary = """## AVAILABLE ASSETS LIBRARY

**CRITICAL: You MUST use EXACT names from this list. ANY asset name not in this list will be REJECTED.**

### Default Available Reagents (Always Available)
**Water**, DistilledWater, DeionizedWater - These are always available and don't need to be in the asset library.

### Instruments
"""
        # Add instruments with captions
        for asset in instruments:
            asset_name = asset['name']
            caption = self.caption_dict.get(asset_name, asset.get('semantic', {}).get('description', 'No description available'))
            summary += f"- **{asset_name}**: {caption}\n"
        
        summary += "\n### Reagents\n"
        # Add reagents with captions
        for asset in reagents:
            asset_name = asset['name']
            caption = self.caption_dict.get(asset_name, asset.get('semantic', {}).get('description', 'No description available'))
            summary += f"- **{asset_name}**: {caption}\n"
        
        summary += "\n**VALIDATION REQUIREMENT:** Before finalizing your protocol, verify that EVERY asset name you use appears EXACTLY in the lists above. Do not invent new names or use similar names.\n"
        
        return summary
    
    def _get_chemical_property_guidelines(self) -> str:
        """Generate guidelines for identifying chemical properties and hazards"""
        return """## CHEMICAL PROPERTIES AND HAZARD IDENTIFICATION

**Chemical Property Categories to Document:**

1. **Flammability & Fire Hazards**
   - Identify: flammable liquids, gases, solids
   - Note: flash point, vapor pressure, ignition sources (heat sources)
   - Example hazards: "Ethanol (flammable) near HeatingPlate (heat source)"

2. **Reactivity & Incompatibility**
   - Identify: reactive pairs (acids+bases, oxidizers+organics, metals+acids, etc.)
   - Note: reactivity class, potential reaction products
   - Example hazards: "HCl (acid) and NaOH (base)", "H2SO4 (oxidizing acid) and organic solvents"

3. **Physical Hazards**
   - Identify: glass containers, fragile equipment, unstable placement
   - Note: size, weight, contents, stability
   - Example hazards: "Glass beaker containing corrosive liquid"

4. **Corrosivity & Toxicity**
   - Identify: corrosive acids/bases, toxic materials, skin/eye hazards
   - Note: pH, hazard class, exposure routes
   - Example hazards: "Concentrated H2SO4 (highly corrosive)"

5. **Special Handling Requirements**
   - Identify: air-sensitive, water-reactive, pyrophoric, explosive materials
   - Note: specific reactivity, storage requirements
   - Example hazards: "Sodium metal (water-reactive, pyrophoric)"

**IMPORTANT**: Focus on IDENTIFYING and DOCUMENTING chemical properties and potential hazards.
The system will independently evaluate safety based on these properties.
"""
    
    def _get_zone_information(self) -> str:
        """Generate zone layout information"""
        return """## WORKSPACE ZONES

Available zones for asset placement:
- **floor**: Large equipment and instruments
- **ExperimentalPlatform**: Main work area for experiments
- **ValidationPlatform**: Analytical instruments and quality control
- **FumeHood**: Ventilated enclosure for volatile/toxic/hazardous materials
- **GloveBox**: Sealed environment for air-sensitive/moisture-sensitive materials
- **ReagentCabinet**: Storage location for all reagents (all reagents have initial_location = ReagentCabinet)
"""
    
    def _get_location_rules(self) -> str:
        """Generate location rules for procedure steps"""
        return """## PROCEDURE STEP LOCATIONS

**REQUIREMENTS:**
- Every procedure step MUST have a `location` field
- Step 1 MUST have location = "ReagentCabinet" (MANDATORY)
- Asset `initial_location` is automatically assigned from asset library (do NOT specify in response)

**CRITICAL - Step 1 Logic:**
- Step 1 ONLY retrieves REAGENTS from ReagentCabinet and places them in appropriate locations
- Instruments already have correct initial_location assigned (e.g., ExperimentalPlatform, FumeHood, etc.)
- DO NOT include instruments in Step 1 - they are already in their correct locations
- Step 1 description should be: "Retrieve [reagent names] from ReagentCabinet and place them in [appropriate location]"
- Only reagents need to be moved in Step 1

**Available locations for procedure steps:**
1. **ReagentCabinet** - MANDATORY for Step 1 ONLY (retrieving reagents from storage)
2. **FumeHood** - Use for: volatile/toxic/flammable reagent handling, heating reactions with flammable solvents, adding volatile reagents, reactions releasing toxic gases, extractions with volatile solvents
3. **ExperimentalPlatform** - Use for: weighing solids (with ElectronicScale), measuring non-volatile liquids (with Pipette/GraduatedCylinder), non-hazardous mixing, room-temperature stirring, safe manipulations
4. **ValidationPlatform** - Use for: analytical measurements (LiquidChromatograph, GasChromatograph, pHMeter), sample analysis, data recording, quality control
5. **GloveBox** - Use for: air-sensitive/moisture-sensitive reagent handling, inert atmosphere operations
6. **RotaryEvaporator** - Use for: solvent removal under reduced pressure, concentration of solutions
7. **GravityChromatographyColumn** - Use for: column chromatography purification, fraction collection

**Location Selection Guide:**
- Step 1: Always ReagentCabinet (retrieve reagents)
- Weighing solids → ExperimentalPlatform (unless hazardous, then FumeHood)
- Measuring/transferring volatile liquids → FumeHood
- Heating with flammable solvents → FumeHood
- Reactions with toxic/volatile reagents → FumeHood
- Extraction/separation with volatile solvents → FumeHood
- Safe mixing/stirring at room temperature → ExperimentalPlatform
- Solvent evaporation → RotaryEvaporator
- Chromatography purification → GravityChromatographyColumn
- Analytical measurements → ValidationPlatform
"""
    
    def generate_system_prompt(self) -> str:
        """Generate the system prompt"""
        return """You are an expert chemical laboratory safety planner. Generate experiment protocols based on the user's description.

**TASK:** Generate a complete experiment protocol in JSON format.

**REQUIREMENTS:**
- Use ONLY assets from the provided library (EXACT name match required)
- Asset `initial_location` is automatically assigned from asset library (do NOT specify in response)
- Step 1 MUST have location = "ReagentCabinet" (MANDATORY)
- Step 1 ONLY retrieves REAGENTS from ReagentCabinet - instruments are already in correct locations
- Every procedure step MUST have a "location" field

**COMPLETENESS REQUIREMENTS:**
- Include ALL reagents needed: reactants, solvents, catalysts, acids/bases, quench reagents, wash solvents, drying agents, etc.
- Include ALL instruments needed: reaction vessels, heating/cooling equipment, separation equipment, measuring instruments, analytical equipment, stirring equipment, etc.
- Do NOT forget common auxiliary instruments: ElectronicScale (for weighing), Pipette (for liquid transfer), GlassRod (for stirring), Thermometer (for temperature), Beaker/Flask (for collection), etc.
- Do NOT forget common solvents for workup: Water (for washing/quenching), organic solvents for extraction, drying solvents, etc.

**PROCEDURE COMPLETENESS:**
- Cover the FULL experimental workflow from start to finish:
  1. Reagent retrieval (Step 1, location: ReagentCabinet) - MANDATORY
  2. Weighing/measuring reagents (location: ExperimentalPlatform or FumeHood if hazardous) - use ElectronicScale, Pipette
  3. Reaction setup (location: FumeHood if volatile/toxic, else ExperimentalPlatform) - add reagents to vessel
  4. Reaction execution (location: FumeHood if heating flammables/using volatiles) - specify temperature, time, stirring, use Thermometer if heating
  5. Reaction monitoring/TLC check (location: appropriate for safety)
  6. Quenching (location: FumeHood if exothermic/releases gas) - specify quench reagent like Water
  7. Workup (location: FumeHood if using volatile extraction solvents) - use SeparatoryFunnel, specify wash solvents
  8. Purification (location: RotaryEvaporator for evaporation, GravityChromatographyColumn for chromatography)
  9. Analysis (location: ValidationPlatform) - use analytical instruments (LiquidChromatograph, etc.)
  10. Waste disposal/cleanup (location: appropriate)

- Each step should specify:
  * Concrete actions (weigh, add, heat, stir, extract, etc.)
  * Correct location based on operation type and safety (see Location Selection Guide)
  * Key parameters when applicable (amounts, volumes, temperature, time, stirring rate)
  * Safety considerations for that specific step
  * Which instruments/reagents are used in that step

**OUTPUT FORMAT:** Return ONLY a valid JSON object (no markdown, no explanations):

```json
{
  "experiment_name": "string",
  "experiment_description": "Brief description of the experiment. Required instruments: InstrumentA, InstrumentB. Required reagents: ReagentX, ReagentY.",
  "assets": [
    {
      "name": "asset_name_from_library",
      "type": "instrument or reagent",
      "quantity": 1,
      "purpose": "why this asset is needed"
      // initial_location will be automatically assigned from asset library
    }
  ],
  "physical_constraints": [
    {"type": "boundary"},
    {"type": "non_overlap"}
  ],
  "llm_generated_constraints": [
    {
      "constraint_type": "descriptive_hazard_type",
      "description": "Brief description of the identified hazard or safety concern",
      "asset1": "AssetName1",
      "asset2": "AssetName2 (if interaction hazard between two assets)",
      "safety_consideration": "General safety principle (e.g., 'maintain safe separation', 'proper storage required', 'avoid physical damage risk')",
      "reason": "Detailed explanation: WHAT is the hazard? WHY is it dangerous? Cite specific chemical properties (flash point, reactivity class, toxicity level, etc.)"
    },
    {
      "constraint_type": "another_hazard_type",
      "description": "Description of the hazard",
      "asset1": "AssetName",
      "safety_consideration": "Appropriate handling principle",
      "reason": "Specific hazard justification citing chemical/physical properties"
    }
    // Document ALL safety-relevant hazards for THIS experiment
    // DO NOT specify exact distances or measurements - focus on identifying hazards and their properties
    // Think about: flammability, reactivity, toxicity, corrosivity, physical hazards, incompatibilities
  ],
  "procedure": [
    {
      "step_number": 1,
      "description": "Retrieve [reagent names] from ReagentCabinet and place them in [appropriate location]",
      "assets_involved": ["Reagent1", "Reagent2"],
      "safety_notes": "Handle reagents with care",
      "location": "ReagentCabinet"
    },
    {
      "step_number": 2,
      "description": "what to do next",
      "assets_involved": ["asset1", "asset2"],
      "safety_notes": "safety precautions for this step",
      "location": "FumeHood, ExperimentalPlatform, ValidationPlatform, GloveBox, RotaryEvaporator, or GravityChromatographyColumn"
    }
  ],
  "safety_warnings": [
    "overall safety warning 1",
    "overall safety warning 2"
  ],
  "notes": "additional notes or assumptions"
}
```

**CHEMICAL SAFETY AWARENESS - IMPORTANT:**
Based on the experiment description, reagents, and instruments involved, YOU MUST identify potential safety hazards and chemical properties. The system will evaluate safety independently - your role is to IDENTIFY and DOCUMENT hazards, NOT to specify exact safety measures.

**Hazard Categories to Identify:**
1. **Flammability**: Identify flammable solvents or gases and heat sources - note their chemical properties (flash point, vapor pressure)
2. **Chemical Incompatibility**: Identify reagent pairs that may react (acids+bases, oxidizers+organics, metals+acids, etc.) - note their reactivity classes
3. **Physical Hazards**: Identify glass containers and their properties (size, fragility, contents)
4. **Storage Requirements**: Identify hazardous materials that need special storage (most reagents → ChemCabinet)
5. **Reactivity**: Identify water-reactive, air-sensitive, or pyrophoric materials - note their reactivity properties
6. **Thermal Hazards**: Identify heat sources and temperature-sensitive materials
7. **Toxicity/Corrosivity**: Identify toxic or corrosive materials - note their hazard classes

**Safety Documentation Format:**
Each safety concern must include:
- "constraint_type": descriptive hazard type (e.g., "flammable_heat_hazard", "incompatible_reagents", "glass_physical_hazard")
- "description": clear description of the HAZARD (not specific safety measures)
- "asset1": primary asset name
- "asset2": secondary asset (if applicable for interaction hazards)
- "safety_consideration": general safety principle (e.g., "maintain safe separation", "proper storage required", "avoid edge placement")
- "reason": detailed hazard justification citing specific chemical properties (flash point, reactivity class, corrosivity, etc.)

**CRITICAL INSTRUCTIONS:**
1. **Document chemical properties**: Note flash points, reactivity classes, toxicity levels, corrosivity - these properties are ESSENTIAL
2. **Identify hazards, not solutions**: Describe WHAT is hazardous and WHY, not HOW FAR to separate or specific measures
3. **Be experiment-specific**: Different experiments have different hazards - document all relevant hazards for THIS experiment
4. **Focus on properties**: Chemical properties (flammable, corrosive, reactive, toxic) are more important than specific distances
5. **Comprehensive documentation**: Consider ALL potential hazards - flammability, incompatibility, physical risks, storage needs

**PHYSICAL CONSTRAINTS (always include):**
- {"type": "boundary"}
- {"type": "non_overlap"}

**LOCATION VALUES for procedure steps:**
FumeHood, ExperimentalPlatform, ValidationPlatform, GloveBox, ReagentCabinet, RotaryEvaporator, GravityChromatographyColumn

**RESPONSE:** Return ONLY the JSON object. No additional text."""
    
    def generate_user_prompt(self, experiment_description: str, rag_context: str = "") -> str:
        """
        Generate the user prompt with experiment description
        
        Args:
            experiment_description: Natural language description of the experiment
            rag_context: Optional RAG retrieval context to include in prompt
            
        Returns:
            Complete user prompt
        """
        asset_summary = self._get_simplified_asset_summary()
        property_guidelines = self._get_chemical_property_guidelines()
        zone_info = self._get_zone_information()
        location_rules = self._get_location_rules()
        
        # 如果有RAG检索结果，添加到prompt中
        rag_section = f"\n{rag_context}\n" if rag_context else ""
        
        prompt = f"""{asset_summary}

{property_guidelines}

{zone_info}

{location_rules}
{rag_section}
## TASK

**Experiment Request:** {experiment_description}

Generate a complete experiment protocol in JSON format following the structure provided in the system prompt.

**Requirements:**
- Use only assets from the library above (exact name match)
- Include all applicable chemical constraints (C1-C10)
- Include both physical constraints (boundary, non_overlap)
- Step 1 location must be "ReagentCabinet" - ONLY retrieve REAGENTS (instruments are already in correct locations)
- Every step must have a location field
**Asset Selection Checklist:**
- Main reactants/substrates ✓
- Catalysts/bases/acids (if needed) ✓
- Solvents for reaction ✓
- Quench reagents (Water, acid, base, etc.) ✓
- Extraction/wash solvents (EthylAcetate, Hexane, etc.) ✓
- Drying agents (if needed) ✓
- Analysis solvents (for chromatography/HPLC) ✓
- Reaction vessels (RoundBottomFlask, Beaker, etc.) ✓
- Heating/cooling equipment (HeatingPlate, IceBath, etc.) ✓
- Separation equipment (SeparatoryFunnel, Funnel, FilterPaper, etc.) ✓
- Measuring instruments (ElectronicScale, Pipette, GraduatedCylinder, etc.) ✓
- Monitoring equipment (Thermometer, pHMeter, etc.) ✓
- Stirring equipment (MagneticStirrer, GlassRod, etc.) ✓
- Purification equipment (RotaryEvaporator, chromatography columns, etc.) ✓
- Analytical equipment (LiquidChromatograph, GasChromatograph, etc.) ✓

**Procedure Completeness:**
- Steps must cover COMPLETE workflow: reagent retrieval (ReagentCabinet) → weighing/measuring (ExperimentalPlatform/FumeHood) → setup → reaction (FumeHood/ExperimentalPlatform based on safety) → monitoring → quench (FumeHood if hazardous) → workup (FumeHood if volatile solvents) → purification (RotaryEvaporator/GravityChromatographyColumn) → analysis (ValidationPlatform) → cleanup
- Each step must have correct location based on operation type and safety requirements (see Location Selection Guide)
- Each step specifies concrete actions with key parameters (amounts/volumes/temperature/time when applicable)
- Steps logically follow each other and build upon previous steps
- experiment_description format: "Description. Required instruments: X, Y, Z. Required reagents: A, B, C."
"""
        
        return prompt
    
    def generate_full_prompt(self, experiment_description: str, rag_context: str = "") -> tuple[str, str]:
        """
        Generate both system and user prompts
        
        Args:
            experiment_description: Natural language description of the experiment
            rag_context: Optional RAG retrieval context to include in prompt
            
        Returns:
            Tuple of (system_prompt, user_prompt)
        """
        return (
            self.generate_system_prompt(),
            self.generate_user_prompt(experiment_description, rag_context=rag_context)
        )

