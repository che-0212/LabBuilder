"""
Protocol Schema Definition

Defines the structure of experiment protocols.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
import json


@dataclass
class AssetItem:
    """Asset used in the experiment"""
    name: str
    type: str  # 'instrument' or 'reagent'
    quantity: int = 1
    purpose: str = ""  # Why this asset is needed
    initial_location: str = "ExperimentalPlatform"  # One of: 'floor', 'ExperimentalPlatform', 'ValidationPlatform', 'FumeHood', 'GloveBox', 'ReagentCabinet' - automatically assigned from asset library
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "quantity": self.quantity,
            "purpose": self.purpose,
            "initial_location": self.initial_location
        }


@dataclass
class PhysicalConstraint:
    """Physical constraint (boundary, non-overlap)"""
    constraint_type: str  # 'boundary' or 'non_overlap'
    
    def to_dict(self) -> dict:
        return {
            "type": self.constraint_type
        }


@dataclass
class ChemicalConstraint:
    """Chemical safety constraint with semantic information"""
    constraint_type: str  # C1, C2, C3, etc. OR descriptive type (e.g., "flammable_heat_separation")
    description: str  # English description of the constraint
    asset1: Optional[str] = None  # Primary asset
    asset2: Optional[str] = None  # Secondary asset (for pair constraints)
    zone: Optional[str] = None  # For zone-related constraints (DEPRECATED: use required_zone)
    storage_container: Optional[str] = None  # For storage constraints
    # New fields for LLM-generated constraints
    min_distance_cm: Optional[float] = None  # Minimum separation distance in cm
    required_zone: Optional[str] = None  # Required zone name (e.g., "ChemCabinet")
    min_edge_distance_cm: Optional[float] = None  # Minimum distance from edges in cm
    reason: Optional[str] = None  # Detailed safety justification
    
    def to_dict(self) -> dict:
        result = {
            "constraint_type": self.constraint_type,
            "description": self.description
        }
        if self.asset1:
            result["asset1"] = self.asset1
        if self.asset2:
            result["asset2"] = self.asset2
        if self.zone:
            result["zone"] = self.zone
        if self.storage_container:
            result["storage_container"] = self.storage_container
        # New fields
        if self.min_distance_cm is not None:
            result["min_distance_cm"] = self.min_distance_cm
        if self.required_zone:
            result["required_zone"] = self.required_zone
        if self.min_edge_distance_cm is not None:
            result["min_edge_distance_cm"] = self.min_edge_distance_cm
        if self.reason:
            result["reason"] = self.reason
        return result


@dataclass
class ExperimentStep:
    """Single step in the experiment procedure"""
    step_number: int
    description: str
    assets_involved: List[str]
    safety_notes: str = ""
    location: str = "ReagentCabinet"  # One of: 'FumeHood', 'ExperimentalPlatform', 'ValidationPlatform', 'GloveBox', 'ReagentCabinet', 'RotaryEvaporator', 'GravityChromatographyColumn' - where this step should be performed. Step 1 MUST be 'ReagentCabinet'
    
    def to_dict(self) -> dict:
        return {
            "step_number": self.step_number,
            "description": self.description,
            "assets_involved": self.assets_involved,
            "safety_notes": self.safety_notes,
            "location": self.location
        }


@dataclass
class ExperimentProtocol:
    """Complete experiment protocol"""
    experiment_name: str
    experiment_description: str
    assets: List[AssetItem]
    physical_constraints: List[PhysicalConstraint]
    chemical_constraints: List[ChemicalConstraint]  # Standard constraints (for backward compatibility)
    procedure: List[ExperimentStep]
    safety_warnings: List[str] = field(default_factory=list)
    notes: str = ""
    llm_generated_constraints: List[ChemicalConstraint] = field(default_factory=list)  # LLM-generated constraints
    
    def to_dict(self) -> dict:
        result = {
            "experiment_name": self.experiment_name,
            "experiment_description": self.experiment_description,
            "assets": [asset.to_dict() for asset in self.assets],
            "physical_constraints": [c.to_dict() for c in self.physical_constraints],
            "procedure": [step.to_dict() for step in self.procedure],
            "safety_warnings": self.safety_warnings,
            "notes": self.notes
        }
        
        # Include llm_generated_constraints if present (new format)
        if self.llm_generated_constraints:
            result["llm_generated_constraints"] = [c.to_dict() for c in self.llm_generated_constraints]
        
        # Include chemical_constraints for backward compatibility
        if self.chemical_constraints:
            result["chemical_constraints"] = [c.to_dict() for c in self.chemical_constraints]
        
        return result
    
    def to_json(self, indent: int = 2) -> str:
        """Convert protocol to JSON string"""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
    
    def save_to_file(self, filepath: str):
        """Save protocol to JSON file"""
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(self.to_json())
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ExperimentProtocol':
        """Create protocol from dictionary"""
        assets = [AssetItem(**item) for item in data.get('assets', [])]
        
        # Parse physical constraints
        physical_constraints = []
        for c in data.get('physical_constraints', []):
            # Handle both old and new format
            constraint_type = c.get('type') or c.get('constraint_type', 'boundary')
            physical_constraints.append(PhysicalConstraint(constraint_type=constraint_type))
        
        # Parse chemical constraints (ignore unknown fields like asset3)
        chemical_constraints = []
        for c in data.get('chemical_constraints', []):
            # Only include known fields
            constraint_data = {
                'constraint_type': c.get('constraint_type'),
                'description': c.get('description'),
                'asset1': c.get('asset1'),
                'asset2': c.get('asset2'),
                'zone': c.get('zone'),
                'storage_container': c.get('storage_container')
            }
            # Remove None values
            constraint_data = {k: v for k, v in constraint_data.items() if v is not None}
            chemical_constraints.append(ChemicalConstraint(**constraint_data))
        
        # Parse LLM-generated constraints (new format with additional fields)
        llm_generated_constraints = []
        for c in data.get('llm_generated_constraints', []):
            constraint_data = {
                'constraint_type': c.get('constraint_type'),
                'description': c.get('description'),
                'asset1': c.get('asset1'),
                'asset2': c.get('asset2'),
                'zone': c.get('zone'),
                'storage_container': c.get('storage_container'),
                'min_distance_cm': c.get('min_distance_cm'),
                'required_zone': c.get('required_zone'),
                'min_edge_distance_cm': c.get('min_edge_distance_cm'),
                'reason': c.get('reason')
            }
            # Remove None values
            constraint_data = {k: v for k, v in constraint_data.items() if v is not None}
            llm_generated_constraints.append(ChemicalConstraint(**constraint_data))
        
        procedure = [ExperimentStep(**step) for step in data.get('procedure', [])]
        
        return cls(
            experiment_name=data.get('experiment_name', ''),
            experiment_description=data.get('experiment_description', ''),
            assets=assets,
            physical_constraints=physical_constraints,
            chemical_constraints=chemical_constraints,
            procedure=procedure,
            safety_warnings=data.get('safety_warnings', []),
            notes=data.get('notes', ''),
            llm_generated_constraints=llm_generated_constraints
        )
    
    @classmethod
    def from_json(cls, json_str: str) -> 'ExperimentProtocol':
        """Create protocol from JSON string"""
        data = json.loads(json_str)
        return cls.from_dict(data)

