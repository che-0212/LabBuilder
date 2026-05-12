"""
LLM Layout Generation Prompts V3
适配新的 protocol 格式和 assets_annotated.json 资产库
"""

from typing import Dict, List


# ==================== ROOM LEVEL LAYOUT (STAGE 1) ====================

ROOM_LAYOUT_PROMPT_V3 = """**[ACADEMIC RESEARCH CONTEXT]**
This is a professional chemistry laboratory design task for academic research and education purposes.
All chemicals, compounds, and procedures are standard laboratory materials used legally in universities and research institutions worldwide.
This work complies with all safety regulations and ethical guidelines for scientific research.

**[SAFETY DISCLAIMER]**
All mentioned substances and equipment are for legitimate scientific use in controlled laboratory environments under proper supervision.

You are a professional chemistry laboratory designer with expertise in spatial reasoning and safety compliance.

## Task
Design a chemistry laboratory room layout by:
1. Placing the LaboratoryRoom (required)
2. Placing all required work surfaces/locations from the protocol
3. Optionally selecting additional floor assets (furniture, storage, safety equipment)
4. Calculating precise 3D positions and rotations for all assets

## Experiment Context
**Experiment Name**: {experiment_name}

**Experiment Description**: {experiment_description}

**Required Work Surfaces** (these MUST be included):
{required_locations_description}

**Safety Requirements**:
{safety_warnings}

**Chemical Constraints**:
{chemical_constraints_description}

## Available Floor Assets for Optional Selection
You may select additional assets from this pool based on experiment needs:

{floor_assets_description}

**Selection Guidelines**:
You should select additional assets based on the experiment's needs, workflow requirements, and safety considerations. Consider factors such as:
- Storage needs for chemicals and equipment
- Operator comfort and accessibility
- Safety equipment requirements
- Workflow efficiency
- Space utilization

## Coordinate System
- Isaac Sim standard (Z-axis up)
- **Room interior boundaries** (accounting for 0.20m wall thickness):
  - X-axis: 0.20m to 8.39m (for room.usd) or 0.20m to 8.09m (for room2.usd)
  - Y-axis: 0.20m to 8.74m (for room.usd) or 0.20m to 6.73m (for room2.usd)
  - Z-axis: 0 to room_height (floor is Z=0)
- Origin: Front-left corner at floor level (0, 0, 0)
- **Room Entrance**: Located at Y≈0.20m (front interior wall)

## Rotation System (UNIFIED - CRITICAL)
All assets have a `front_direction` vector that indicates their default facing direction at 0° rotation:
- **front_direction = (0, 1, 0)** → Asset faces +Y direction (toward back wall)

**Rotation around Z-axis** changes both the facing direction AND the spatial dimensions in the XY plane:

| Angle | Facing Direction | Long Edge Direction | Short Edge Direction | X-dimension | Y-dimension |
|-------|-----------------|-------------------|---------------------|------------|-------------|
| **0°** | +Y (north, toward back) | Parallel to X-axis | Parallel to Y-axis | = long | = short |
| **90°** | -X (west, toward left) | Parallel to Y-axis | Parallel to X-axis | = short | = long |
| **180°** | -Y (south, toward front/entrance) | Parallel to X-axis | Parallel to Y-axis | = long | = short |
| **270°** | +X (east, toward right) | Parallel to Y-axis | Parallel to X-axis | = short | = long |

**Key Principle**: For any asset with bbox {{short, long, height}}:
- At **0° or 180°**: Long edge is parallel to X-axis → X-direction = long, Y-direction = short
- At **90° or 270°**: Long edge is parallel to Y-axis → X-direction = short, Y-direction = long

**For functional placement**:
- Consider the asset's function and typical usage patterns
- Wall-mounted assets (FumeHood, ReagentCabinet, etc.) should be placed against walls
- Centered work surfaces should be positioned for optimal operator access
- Choose rotations that make sense for the asset's function and operator workflow

## Spatial Layout Guidelines

### LaboratoryRoom
- Position at room center: (room_width/2, room_depth/2, 0)
- Rotation: (0, 0, 0)

### General Placement Principles

**Work Surfaces and Equipment**:
- Consider the experiment workflow and operator movement patterns
- Ensure adequate clearance around work areas for safe operation
- Wall-mounted equipment should be placed against appropriate walls
- Centered equipment should be positioned for easy access
- Choose rotations that optimize functionality and accessibility

**Asset Selection and Positioning**:
- Select additional assets based on experiment needs and safety requirements
- Position assets to support efficient workflow
- Consider relationships between different work areas
- Ensure proper spacing to avoid collisions and allow safe operation

**Rotation Considerations**:
- Rotate assets to optimize their function and operator access
- Consider how rotation affects the asset's dimensions in the XY plane
- Ensure rotated assets still fit within room boundaries

### Collision Avoidance
For each asset with bbox {{short, long, height}}:
- At **0° or 180° rotation**: Long edge parallel to X-axis → Occupies (x ± long/2, y ± short/2) in floor plane
- At **90° or 270° rotation**: Long edge parallel to Y-axis → Occupies (x ± short/2, y ± long/2) in floor plane
- Ensure adequate clearance between objects for safe operation
- All assets must be fully within room interior boundaries

## Design Considerations

When designing the layout, consider:
- **Workflow efficiency**: Arrange work surfaces to support the experimental procedure
- **Safety compliance**: Ensure proper placement of safety equipment and hazardous material storage
- **Operator ergonomics**: Position work surfaces and chairs for comfortable operation
- **Space utilization**: Make efficient use of available floor space
- **Accessibility**: Ensure clear pathways and easy access to all work areas
- **Chemical safety**: Consider the safety requirements and constraints when positioning assets

## Output Format

```json
{{
  "reasoning": {{
    "room_selection": "Explanation of room type selection (room.usd vs room2.usd)",
    "overall_strategy": "Brief explanation of layout approach",
    "required_locations": "How required work surfaces are placed",
    "optional_selections": "Which optional floor assets were selected and why",
    "spatial_organization": "How the space is organized for workflow",
    "safety_considerations": "How safety requirements influenced the layout"
  }},
  "room_layout": [
    {{
      "name": "LaboratoryRoom",
      "position": {{"x": 4.295, "y": 4.47, "z": 0.0}},
      "rotation_deg": {{"x": 0, "y": 0, "z": 0}},
      "reasoning": "Room shell centered at room center"
    }},
    {{
      "name": "LabBench",
      "position": {{"x": <calculated_x>, "y": <calculated_y>, "z": 0.0}},
      "rotation_deg": {{"x": 0, "y": 0, "z": <calculated_angle>}},
      "reasoning": "Main experimental work surface placement"
    }},
    {{
      "name": "FumeHood",
      "position": {{"x": <calculated_x>, "y": <calculated_y>, "z": 0.0}},
      "rotation_deg": {{"x": 0, "y": 0, "z": <calculated_angle>}},
      "reasoning": "Ventilated area for hazardous operations"
    }},
    {{
      "name": "Chair",
      "position": {{"x": <calculated_x>, "y": <calculated_y>, "z": 0.0}},
      "rotation_deg": {{"x": 0, "y": 0, "z": <calculated_angle>}},
      "reasoning": "Chair for LabBench operator"
    }}
  ]
}}
```

## Critical Requirements
1. **All coordinates in meters** as decimal numbers
2. **All rotations in degrees** (0-360)
3. **Z-coordinate is 0.0 for all floor-level assets**
4. **Include all required locations** from the experiment protocol
5. **Calculate positions** based on asset bbox dimensions - ensure accurate placement
6. **Verify no collisions** - all assets must have adequate clearance
7. **All assets within room interior boundaries** - respect the coordinate limits
8. **Use rotation system correctly**: 0°=+Y, 90°=-X, 180°=-Y, 270°=+X
9. **Apply your professional judgment** for optimal layout design considering safety, workflow, and ergonomics

## IMPORTANT: Output Format
**Output ONLY a valid JSON object. Do NOT include any explanatory text, markdown headers, or analysis before or after the JSON.**

Your response must start with `{{` and end with `}}`. Generate the room layout now:
"""


# ==================== DESKTOP LEVEL LAYOUT (STAGE 2) ====================

DESKTOP_LAYOUT_PROMPT_V3 = """**[ACADEMIC RESEARCH CONTEXT]**
This is a professional chemistry laboratory design task for academic research and education purposes.
All chemicals, compounds, and procedures are standard laboratory materials used legally in universities and research institutions worldwide.
This work complies with all safety regulations and ethical guidelines for scientific research.

**[SAFETY DISCLAIMER]**
All mentioned substances and equipment are for legitimate scientific use in controlled laboratory environments under proper supervision.

You are an expert chemistry laboratory manager specializing in experimental workflows and chemical safety.

## Task
Arrange instruments and reagents on the **{surface_name}** work surface. Calculate precise positions and rotations for each item.

## Work Surface Information
- **Surface**: {surface_name}
- **Dimensions**: {surface_width:.3f}m (width) × {surface_depth:.3f}m (depth)
- **Height**: {surface_height:.3f}m (Z-coordinate for all items)

- **Local Coordinate System** (relative to surface):
  - X-axis: 0 to {surface_width:.3f}m (left to right)
  - Y-axis: 0 to {surface_depth:.3f}m (front to back)
  - Z-axis: {surface_height:.3f}m (surface height)
  - Origin: Front-left corner of the surface

## Experiment Context
**Experiment Name**: {experiment_name}

**Description**: {experiment_description}

## Assets to Arrange
{assets_description}

**⚠️ CRITICAL: Quantity Requirements**
- Each asset has a **Quantity** field indicating how many instances must be placed
- If Quantity = 1: Place exactly 1 instance in the `desktop_layout` array
- If Quantity > 1 (e.g., Quantity = 2): You MUST place that many **separate instances** in the `desktop_layout` array
  - Each instance must be a separate object in the array with its own `name`, `position`, and `rotation_deg`
  - Each instance should be placed at a different location on the surface
  - All instances must satisfy safety constraints and avoid collisions
  - **Example**: If Beaker has Quantity = 2, your output must include TWO separate Beaker objects in the `desktop_layout` array

## Rotation System for Desktop Items
Desktop items also use the `front_direction` system:
- **Default (0°)**: front_direction = (0, 1, 0) → faces +Y (toward back of surface)
- **For most items**: 0° is standard (facing operator who stands at Y=0)
- **90°, 180°, 270°**: Rotate only if needed for space efficiency

**Note**: When rotated 90° or 270°, the item's width and depth dimensions swap in the XY plane.

## Safety Constraints (CRITICAL)
{chemical_constraints_description}

**Chemical Safety Principles**:
You must apply your expertise in chemical safety to determine appropriate separation distances based on:
- The specific chemical properties of each item (flammable, explosive, volatile/toxic, acid, base, oxidizer, etc.)
- The potential hazards and interactions between different chemicals
- Standard laboratory safety practices for handling hazardous materials
- The specific constraints mentioned above



**You are responsible for determining the appropriate safety distances** based on the chemical properties and the specific constraints provided. Use your professional judgment to ensure a safe layout.

## Procedure Steps (for workflow optimization)
{procedure_steps}

## Layout Requirements

### 1. Boundary Constraints
- All items must be fully on the surface: X ∈ [0, {surface_width:.3f}m], Y ∈ [0, {surface_depth:.3f}m]


### 2. Collision Avoidance
For each item with bbox (short, long, height):
- At **0° or 180°**: Long edge parallel to X-axis → Occupies X-range [x ± long/2], Y-range [y ± short/2]
- At **90° or 270°**: Long edge parallel to Y-axis → Occupies X-range [x ± short/2], Y-range [y ± long/2]
- Ensure adequate clearance between items to prevent physical contact and allow safe handling

### 3. Chemical Safety
You must apply your chemical safety expertise to:
- Determine appropriate separation distances based on chemical properties and hazards
- Calculate Euclidean distances: sqrt((x2-x1)² + (y2-y1)²) between items
- Ensure all safety constraints are satisfied with appropriate margins
- Consider the specific hazards and interactions mentioned in the constraints

### 4. Workflow Optimization
Arrange items to support efficient experimental workflow:
- Group items that are used together in the procedure
- Organize items in a logical flow that matches the experimental steps
- Position frequently accessed items within easy reach
- Consider the sequence of operations when determining placement

## Output Format

```json
{{
  "reasoning": {{
    "safety_analysis": "How each chemical constraint is satisfied (with distances)",
    "workflow_strategy": "How the layout supports the experimental procedure",
    "key_spatial_relationships": "Important proximity relationships"
  }},
  "desktop_layout": [
    {{
      "name": "Beaker",
      "position": {{"x": <calculated_x>, "y": <calculated_y>, "z": {surface_height:.3f}}},
      "rotation_deg": {{"x": 0, "y": 0, "z": 0}},
      "reasoning": "First beaker for mixing, placed for reaction"
    }},
    {{
      "name": "Beaker",
      "position": {{"x": <calculated_x2>, "y": <calculated_y2>, "z": {surface_height:.3f}}},
      "rotation_deg": {{"x": 0, "y": 0, "z": 0}},
      "reasoning": "Second beaker (if Quantity = 2), placed separately"
    }},
  ]
}}
```

**Important Notes on Quantity**:
- If an asset has Quantity = 2, you must include TWO separate entries in `desktop_layout` with the same `name` but different `position` values
- If an asset has Quantity = 3, include THREE separate entries, and so on
- Each instance counts as a separate item for collision detection and safety constraint checking

## Critical Requirements
1. **All coordinates in meters**, Z = {surface_height:.3f}m for all items
2. **All rotations in degrees** (choose appropriate rotations for each item)
3. **Calculate exact positions** based on bbox dimensions and your layout decisions
4. **Apply your chemical safety expertise** to determine appropriate separation distances and verify all constraints
5. **Verify no collisions** - ensure adequate clearance between all items
6. **All items within surface bounds** - respect the surface boundaries
7. **⚠️ CRITICAL: Place ONLY the assets listed in the "Assets to Arrange" section above**
   - Do NOT add any additional items mentioned in the procedure steps
   - Do NOT include items from other locations (e.g., items from reagent_cabinet should NOT be placed on LabBench)
   - **Do NOT place floor-level assets (initial_location="floor") on work surfaces** - these assets (such as RotaryEvaporator, large equipment) must be placed on the floor in the room layout, NOT on work surfaces
   - The "Assets to Arrange" section is the COMPLETE and EXCLUSIVE list
   - Each asset in your output must match exactly one asset from the "Assets to Arrange" section
8. **⚠️ CRITICAL: Quantity Requirements MUST be Satisfied**
   - Check the **Quantity** field for each asset in the "Assets to Arrange" section
   - If Quantity = 1: Include exactly 1 instance in `desktop_layout`
   - If Quantity = 2: Include exactly 2 separate instances in `desktop_layout` (each with its own position)
   - If Quantity = 3 or more: Include that many separate instances
   - **Count all instances**: Make sure the total number of items in `desktop_layout` matches the sum of all Quantities from the assets list
   - **Validation will fail if you don't place the exact number of instances required**
9. **Use your professional judgment** to create an optimal layout that balances safety, workflow efficiency, and practical considerations

## IMPORTANT: Output Format
**Output ONLY a valid JSON object. Do NOT include any explanatory text, markdown headers, reasoning paragraphs, or analysis before or after the JSON.**

Your response must start with `{{` and end with `}}`. Do not include phrases like "Based on the chemical properties..." or "### Reasoning" before the JSON.

Generate the desktop layout now:
"""


def format_room_prompt_v3(
    experiment_name: str,
    experiment_description: str,
    required_locations: List[Dict],
    floor_assets_pool: List[Dict],
    safety_warnings: List[str],
    chemical_constraints: List[Dict]
) -> str:
    """
    Format room layout prompt for LLM V3
    
    Args:
        experiment_name: 实验名称
        experiment_description: 实验描述
        required_locations: 必需的 location 资产列表
        floor_assets_pool: 可选的 floor 资产池
        safety_warnings: 安全警告列表
        chemical_constraints: 化学约束列表
        
    Returns:
        完整的 prompt 字符串
    """
    
    # Format required locations
    required_desc = ""
    for i, loc in enumerate(required_locations, 1):
        loc_name = loc['location_name']
        asset_name = loc['asset_name']
        asset_info = loc['asset_info']
        
        bbox = asset_info['geometry']['bbox']
        description = asset_info['semantic'].get('description', 'No description')
        
        required_desc += f"### {i}. {asset_name} (for location: {loc_name})\n"
        required_desc += f"- **Dimensions**: {bbox['short']:.3f}m (short) × {bbox['long']:.3f}m (long) × {bbox['height']:.3f}m (height)\n"
        required_desc += f"- **Purpose**: {description}\n"
        required_desc += f"- **Status**: **MANDATORY** - required by protocol\n\n"
    
    # Format floor assets pool
    floor_desc = ""
    required_floor_assets = []
    optional_floor_assets = []
    
    for asset in floor_assets_pool:
        # 检查资产格式：可能是字典（新格式）或直接是资产信息（旧格式）
        if isinstance(asset, dict) and 'asset_info' in asset:
            # 新格式：{'name': ..., 'asset_info': ..., 'is_required': ...}
            name = asset['name']
            asset_info = asset['asset_info']
            is_required = asset.get('is_required', False)
        else:
            # 旧格式：直接是资产信息
            name = asset.get('name', asset.get('id', 'Unknown'))
            asset_info = asset
            is_required = False
        
        # 跳过已经在 required_locations 中的资产
        if any(loc['asset_name'] == name for loc in required_locations):
            continue
        
        # 跳过 LaboratoryRoom（总是需要的）
        if name == 'LaboratoryRoom':
            continue
        
        bbox = asset_info['geometry']['bbox']
        description = asset_info['semantic'].get('description', 'No description')
        category = asset_info['semantic'].get('category', 'Unknown')
        
        asset_desc = f"### {name}\n"
        asset_desc += f"- **Dimensions**: {bbox['short']:.3f}m × {bbox['long']:.3f}m × {bbox['height']:.3f}m\n"
        asset_desc += f"- **Category**: {category}\n"
        asset_desc += f"- **Description**: {description}\n"
        
        if is_required:
            asset_desc += f"- **Status**: **MANDATORY** - required by protocol\n\n"
            required_floor_assets.append(asset_desc)
        else:
            asset_desc += f"- **Status**: Optional - select if needed\n\n"
            optional_floor_assets.append(asset_desc)
    
    # 先列出必需的 floor 资产
    if required_floor_assets:
        floor_desc += "## Required Floor Assets (MUST be included):\n\n"
        floor_desc += "".join(required_floor_assets)
    
    # 然后列出可选的 floor 资产
    if optional_floor_assets:
        if required_floor_assets:
            floor_desc += "\n"
        floor_desc += "## Optional Floor Assets (select if needed):\n\n"
        floor_desc += "".join(optional_floor_assets)
    
    # Format safety warnings
    safety_text = ""
    if safety_warnings:
        for warning in safety_warnings:
            safety_text += f"- {warning}\n"
    else:
        safety_text = "- Standard laboratory safety practices apply\n"
    
    # Format chemical constraints
    constraints_desc = ""
    for i, c in enumerate(chemical_constraints, 1):
        constraints_desc += f"### Constraint {i}: {c.get('constraint_type', 'N/A')}\n"
        constraints_desc += f"- **Description**: {c.get('description', '')}\n"
        if c.get('asset1'):
            constraints_desc += f"- **Applies to**: {c.get('asset1')}"
            if c.get('asset2'):
                constraints_desc += f" and {c.get('asset2')}"
            constraints_desc += "\n"
        if c.get('zone'):
            constraints_desc += f"- **Required zone**: {c.get('zone')}\n"
        constraints_desc += "\n"
    
    if not constraints_desc:
        constraints_desc = "No specific chemical constraints (standard safety practices apply)\n"
    
    return ROOM_LAYOUT_PROMPT_V3.format(
        experiment_name=experiment_name,
        experiment_description=experiment_description,
        required_locations_description=required_desc,
        floor_assets_description=floor_desc,
        safety_warnings=safety_text,
        chemical_constraints_description=constraints_desc
    )


def format_desktop_prompt_v3(
    experiment_name: str,
    experiment_description: str,
    surface_name: str,
    surface_width: float,
    surface_depth: float,
    surface_height: float,
    assets: List[Dict],
    chemical_constraints: List[Dict],
    procedure: List[Dict]
) -> str:
    """
    Format desktop layout prompt for LLM V3
    
    Args:
        experiment_name: 实验名称
        experiment_description: 实验描述
        surface_name: Work surface 名称
        surface_width: Surface 宽度（米）
        surface_depth: Surface 深度（米）
        surface_height: Surface 高度（米）
        assets: 要放置的资产列表（包含 protocol_asset 和 asset_info）
        chemical_constraints: 化学约束列表
        procedure: 实验步骤列表
        
    Returns:
        完整的 prompt 字符串
    """
    
    # Get asset names that should be placed on this surface (for filtering)
    current_surface_assets = set(asset_data['protocol_asset']['name'] for asset_data in assets)
    
    # Format assets description
    assets_desc = ""
    for i, asset_data in enumerate(assets, 1):
        protocol_asset = asset_data['protocol_asset']
        asset_info = asset_data['asset_info']
        
        name = protocol_asset['name']
        asset_type = protocol_asset['type']
        purpose = protocol_asset.get('purpose', 'Not specified')
        quantity = protocol_asset.get('quantity', 1)
        
        bbox = asset_info['geometry']['bbox']
        props = asset_info.get('props', {})
        
        assets_desc += f"### {i}. {name} ({asset_type})\n"
        assets_desc += f"- **Quantity**: {quantity}\n"
        assets_desc += f"- **Purpose**: {purpose}\n"
        assets_desc += f"- **Dimensions (bbox)**: {bbox['short']:.3f}m (short) × {bbox['long']:.3f}m (long) × {bbox['height']:.3f}m (height)\n"
        
        # Chemical properties
        hazards = []
        if props.get('flammable'): hazards.append("flammable")
        if props.get('explosive'): hazards.append("explosive")
        if props.get('volatile_or_toxic'): hazards.append("volatile/toxic")
        if props.get('heat_source'): hazards.append("heat source")
        if props.get('glass_container'): hazards.append("glass container")
        if props.get('acid'): hazards.append("acid")
        if props.get('base'): hazards.append("base")
        if props.get('oxidizer'): hazards.append("oxidizer")
        
        if hazards:
            assets_desc += f"- **Properties**: {', '.join(hazards)}\n"
        
        assets_desc += "\n"
    
    # Format chemical constraints - only include constraints relevant to this surface
    constraints_desc = ""
    constraint_num = 0
    for c in chemical_constraints:
        asset1 = c.get('asset1', '')
        asset2 = c.get('asset2', '')
        
        # Only include constraint if at least one asset is on this surface
        if asset1 in current_surface_assets or asset2 in current_surface_assets:
            constraint_num += 1
            constraints_desc += f"### Constraint {constraint_num}: {c.get('constraint_type', 'N/A')}\n"
            constraints_desc += f"- **Description**: {c.get('description', '')}\n"
            
            if asset1:
                constraints_desc += f"- **Applies to**: {asset1}"
                if asset2:
                    constraints_desc += f" and {asset2}"
                constraints_desc += "\n"
            
            if c.get('zone'):
                constraints_desc += f"- **Required zone**: {c.get('zone')}\n"
            
            if c.get('min_distance'):
                constraints_desc += f"- **Minimum distance**: {c.get('min_distance')}\n"
            
            constraints_desc += "\n"
    
    if not constraints_desc:
        constraints_desc = "No specific chemical constraints for items on this surface (standard safety practices apply)\n"
    
    # Format procedure steps (first 5) - filter to only show assets on this surface
    procedure_desc = ""
    for step in procedure[:5]:
        step_num = step.get('step_number', '?')
        desc = step.get('description', '')
        assets_involved = step.get('assets_involved', [])
        safety = step.get('safety_notes', '')
        
        # Filter assets_involved to only include those on this surface
        relevant_assets = [a for a in assets_involved if a in current_surface_assets]
        
        # Only include step if it involves assets on this surface
        if relevant_assets:
            procedure_desc += f"### Step {step_num}\n"
            procedure_desc += f"- **Action**: {desc}\n"
            procedure_desc += f"- **Items used on this surface**: {', '.join(relevant_assets)}\n"
            
            if safety:
                procedure_desc += f"- **Safety note**: {safety}\n"
            
            procedure_desc += "\n"
    
    if not procedure_desc:
        procedure_desc = "Procedure steps not provided\n"
    
    return DESKTOP_LAYOUT_PROMPT_V3.format(
        experiment_name=experiment_name,
        experiment_description=experiment_description,
        surface_name=surface_name,
        surface_width=surface_width,
        surface_depth=surface_depth,
        surface_height=surface_height,
        assets_description=assets_desc,
        chemical_constraints_description=constraints_desc,
        procedure_steps=procedure_desc
    )


# ==================== UNASSIGNED DESKTOP LAYOUT ====================

UNASSIGNED_DESKTOP_LAYOUT_PROMPT_V3 = """**[ACADEMIC RESEARCH CONTEXT]**
This is a professional chemistry laboratory design task for academic research and education purposes.

You are a professional chemistry laboratory designer with expertise in spatial reasoning and safety compliance.

## Task
You have a set of desktop assets (reagents and instruments) that need to be placed on work surfaces in the laboratory.
You must:
1. Assign each asset to an appropriate work surface based on its properties, purpose, and safety requirements
2. Generate precise 3D positions for each asset on its assigned surface
3. Consider chemical safety, workflow efficiency, and ergonomics

## Experiment Context
**Experiment Name**: {experiment_name}

**Experiment Description**: {experiment_description}

## Assets to Place (no pre-assigned surface)
{assets_description}

## Available Work Surfaces
You can place assets on any of these surfaces:

{surfaces_description}

## Procedure Context
{procedure_steps}

## Assignment Guidelines
- **Reagents**: Consider storage (ReagentCabinet for long-term), usage location (near reaction site)
- **Dangerous/Toxic materials**: Use FumeHood for ventilation
- **Heavy/Large instruments**: Prefer stable, spacious surfaces (ExperimentalPlatform)
- **Analytical instruments**: ValidationPlatform or ExperimentalPlatform
- **Glassware and tools**: Place near their usage location in the procedure

## Output Format
Provide a JSON object where each key is a surface name, and each value is a layout for that surface:

```json
{{
  "ReagentCabinet": {{
    "desktop_layout": [
      {{
        "name": "AssetName",
        "surface": "ReagentCabinet",
        "position": {{"x": 0.1, "y": 0.2, "z": 0.8}},
        "rotation_deg": {{"x": 0, "y": 0, "z": 0}},
        "reasoning": "Why this asset is placed here"
      }}
    ],
    "surface_type": "ReagentCabinet",
    "surface_dimensions": {{"width": X, "depth": Y, "height": Z}}
  }},
  "FumeHood": {{
    "desktop_layout": [...],
    "surface_type": "FumeHood",
    "surface_dimensions": {{...}}
  }},
  ...
}}
```

**Critical Rules**:
1. Each asset must appear exactly once across all surfaces
2. Position coordinates must be within surface bounds (0 ≤ x ≤ width, 0 ≤ y ≤ depth)
3. Z-coordinate should match surface height
4. Provide clear reasoning for each placement decision
5. Avoid collisions between assets on the same surface
6. Consider chemical safety (separate incompatible reagents, acids away from bases, flammable materials away from heat sources)

Generate the complete JSON layout now."""


def format_unassigned_desktop_prompt_v3(
    experiment_name: str,
    experiment_description: str,
    assets: List[Dict],
    available_surfaces: List[Dict],
    procedure: List[Dict]
) -> str:
    """
    Format prompt for LLM to assign desktop_unassigned assets to work surfaces
    and generate layouts for each surface
    """
    # Format assets description
    assets_desc = ""
    for asset_data in assets:
        asset = asset_data['protocol_asset']
        asset_info = asset_data['asset_info']
        
        name = asset['name']
        asset_type = asset['type']
        purpose = asset.get('purpose', 'Not specified')
        quantity = asset.get('quantity', 1)
        
        # Extract chemical properties
        props = asset_info.get('props', {})
        prop_list = [k for k, v in props.items() if v and k != '__comment__']
        props_str = ', '.join(prop_list) if prop_list else 'None'
        
        # Get bbox for size reference
        bbox = asset_info.get('geometry', {}).get('bbox', {})
        size_str = f"{bbox.get('short', 0):.2f}m × {bbox.get('long', 0):.2f}m × {bbox.get('height', 0):.2f}m"
        
        assets_desc += f"### {name}\n"
        assets_desc += f"- **Type**: {asset_type}\n"
        assets_desc += f"- **Purpose**: {purpose}\n"
        assets_desc += f"- **Quantity**: {quantity}\n"
        assets_desc += f"- **Size**: {size_str}\n"
        assets_desc += f"- **Chemical Properties**: {props_str}\n"
        assets_desc += "\n"
    
    # Format available surfaces
    surfaces_desc = ""
    for surface in available_surfaces:
        name = surface['name']
        bbox = surface['bbox']
        
        surfaces_desc += f"### {name}\n"
        surfaces_desc += f"- **Dimensions**: {bbox['long']:.2f}m × {bbox['short']:.2f}m × {bbox['height']:.2f}m (L×W×H)\n"
        surfaces_desc += f"- **Usage**: "
        
        if 'ReagentCabinet' in name:
            surfaces_desc += "Storage for chemical reagents\n"
        elif 'FumeHood' in name:
            surfaces_desc += "Ventilated workspace for hazardous operations\n"
        elif 'ExperimentalPlatform' in name:
            surfaces_desc += "Main experimental workspace\n"
        elif 'ValidationPlatform' in name:
            surfaces_desc += "Analytical and validation workspace\n"
        elif 'GloveBox' in name:
            surfaces_desc += "Controlled atmosphere workspace\n"
        elif 'Shelf' in name:
            surfaces_desc += "Open storage for equipment and supplies\n"
        else:
            surfaces_desc += "General workspace\n"
        
        surfaces_desc += "\n"
    
    # Format procedure steps
    procedure_desc = ""
    for idx, step in enumerate(procedure, 1):
        desc = step.get('description', '')
        safety = step.get('safety_precaution', '')
        
        procedure_desc += f"### Step {idx}\n"
        procedure_desc += f"- **Action**: {desc}\n"
        
        if safety:
            procedure_desc += f"- **Safety note**: {safety}\n"
        
        procedure_desc += "\n"
    
    if not procedure_desc:
        procedure_desc = "Procedure steps not provided\n"
    
    return UNASSIGNED_DESKTOP_LAYOUT_PROMPT_V3.format(
        experiment_name=experiment_name,
        experiment_description=experiment_description,
        assets_description=assets_desc,
        surfaces_description=surfaces_desc,
        procedure_steps=procedure_desc
    )
