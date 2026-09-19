from pydantic import ConfigDict
"""
Production-ready pricing calculator package.
Implements a flexible pricing calculator with support for multiple pricing models,
discounts, taxes, and comprehensive input validation.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union, Any
from enum import Enum
import json
import math
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from pydantic import BaseModel, Field, validator, ValidationError
from typing_extensions import Literal


class PricingModel(str, Enum):
    """Supported pricing models."""
    FLAT_RATE = "flat_rate"
    PER_UNIT = "per_unit"
    TIERED = "tiered"
    VOLUME_DISCOUNT = "volume_discount"
    SUBSCRIPTION = "subscription"


class DiscountType(str, Enum):
    """Types of discounts that can be applied."""
    PERCENTAGE = "percentage"
    FIXED_AMOUNT = "fixed_amount"
    BUY_X_GET_Y = "buy_x_get_y"


class TaxType(str, Enum):
    """Types of taxes that can be applied."""
    SALES_TAX = "sales_tax"
    VAT = "vat"
    GST = "gst"


@dataclass
class PriceTier:
    """Represents a pricing tier for tiered or volume discount pricing."""
    min_quantity: int
    max_quantity: Optional[int] = None
    unit_price: Decimal = Decimal("0.00")
    
    def __post_init__(self):
        """Validate tier data after initialization."""
        if self.min_quantity < 0:
            raise ValueError("min_quantity must be non-negative")
        if self.max_quantity is not None and self.max_quantity < self.min_quantity:
            raise ValueError("max_quantity must be greater than or equal to min_quantity")
        if self.unit_price < Decimal("0.00"):
            raise ValueError("unit_price must be non-negative")


@dataclass
class Discount:
    """Represents a discount to be applied to a price calculation."""
    discount_type: DiscountType
    value: Decimal
    min_purchase: Optional[Decimal] = None
    max_discount: Optional[Decimal] = None
    code: Optional[str] = None
    
    def __post_init__(self):
        """Validate discount data after initialization."""
        if self.value <= Decimal("0.00"):
            raise ValueError("Discount value must be positive")
        if self.discount_type == DiscountType.PERCENTAGE and self.value > Decimal("100.00"):
            raise ValueError("Percentage discount cannot exceed 100%")
        if self.max_discount is not None and self.max_discount < Decimal("0.00"):
            raise ValueError("max_discount must be non-negative")


@dataclass
class Tax:
    """Represents a tax to be applied to a price calculation."""
    tax_type: TaxType
    rate: Decimal
    jurisdiction: Optional[str] = None
    
    def __post_init__(self):
        """Validate tax data after initialization."""
        if self.rate < Decimal("0.00") or self.rate > Decimal("100.00"):
            raise ValueError("Tax rate must be between 0 and 100")
        if self.tax_type == TaxType.SALES_TAX and self.jurisdiction is None:
            raise ValueError("Sales tax requires a jurisdiction")


class PricingInput(BaseModel):
    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True, extra="allow")
    """Input model for price calculation with validation."""
    pricing_model: PricingModel
    base_price: Decimal = Field(..., gt=0, description="Base price must be positive")
    quantity: int = Field(..., gt=0, description="Quantity must be positive")
    tiers: Optional[List[PriceTier]] = None
    discounts: Optional[List[Discount]] = None
    taxes: Optional[List[Tax]] = None
    currency: str = Field("USD", pattern="^[A-Z]{3}$")
    customer_id: Optional[str] = None
    
    @validator('tiers')
    def validate_tiers(cls, v, values):
        """Validate that tiers are properly ordered and cover the range."""
        if v is None:
            return v
        
        if values.get('pricing_model') not in [PricingModel.TIERED, PricingModel.VOLUME_DISCOUNT]:
            raise ValueError("Tiers are only applicable for tiered or volume discount pricing")
        
        # Sort tiers by min_quantity
        sorted_tiers = sorted(v, key=lambda x: x.min_quantity)
        
        # Check for gaps or overlaps
        for i in range(len(sorted_tiers) - 1):
            current_max = sorted_tiers[i].max_quantity
            next_min = sorted_tiers[i + 1].min_quantity
            
            if current_max is not None and current_max >= next_min:
                raise ValueError("Tier ranges must not overlap")
            if current_max is not None and current_max + 1 != next_min:
                raise ValueError("Tier ranges must be contiguous")
        
        return sorted_tiers
    
    @validator('discounts')
    def validate_discounts(cls, v):
        """Validate discount codes are unique."""
        if v is None:
            return v
        
        codes = [d.code for d in v if d.code is not None]
        if len(codes) != len(set(codes)):
            raise ValueError("Discount codes must be unique")
        
        return v
    
class PricingCalculator:
    """
    Main pricing calculator class that handles all pricing calculations
    with comprehensive validation and deterministic output.
    """
    
    def __init__(self):
        """Initialize the pricing calculator."""
        self._calculation_history: List[Dict[str, Any]] = []
    
    def calculate_price(self, input_data: PricingInput) -> Dict[str, Any]:
        """
        Calculate the final price based on input parameters.
        
        Args:
            input_data: Validated pricing input
            
        Returns:
            Dictionary containing all pricing components and final price
        """
        try:
            # Calculate base price based on pricing model
            subtotal = self._calculate_subtotal(input_data)
            
            # Apply discounts
            discount_amount, applied_discounts = self._apply_discounts(
                subtotal, input_data.discounts or []
            )
            discounted_subtotal = subtotal - discount_amount
            
            # Apply taxes
            tax_amount, applied_taxes = self._apply_taxes(
                discounted_subtotal, input_data.taxes or []
            )
            total = discounted_subtotal + tax_amount
            
            # Round all monetary values to 2 decimal places
            subtotal = self._round_currency(subtotal)
            discount_amount = self._round_currency(discount_amount)
            discounted_subtotal = self._round_currency(discounted_subtotal)
            tax_amount = self._round_currency(tax_amount)
            total = self._round_currency(total)
            
            result = {
                "subtotal": float(subtotal),
                "discount_amount": float(discount_amount),
                "applied_discounts": applied_discounts,
                "discounted_subtotal": float(discounted_subtotal),
                "tax_amount": float(tax_amount),
                "applied_taxes": applied_taxes,
                "total": float(total),
                "currency": input_data.currency,
                "quantity": input_data.quantity,
                "pricing_model": input_data.pricing_model.value,
                "calculation_id": f"calc_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}",
                "timestamp": datetime.now().isoformat()
            }
            
            # Store in history
            self._calculation_history.append(result)
            
            return result
            
        except Exception as e:
            raise ValueError(f"Price calculation failed: {str(e)}")
    
    def _calculate_subtotal(self, input_data: PricingInput) -> Decimal:
        """Calculate subtotal based on pricing model."""
        if input_data.pricing_model == PricingModel.FLAT_RATE:
            return input_data.base_price
        
        elif input_data.pricing_model == PricingModel.PER_UNIT:
            return input_data.base_price * Decimal(str(input_data.quantity))
        
        elif input_data.pricing_model == PricingModel.TIERED:
            if not input_data.tiers:
                raise ValueError("Tiered pricing requires tiers")
            return self._calculate_tiered_price(input_data.base_price, input_data.quantity, input_data.tiers)
        
        elif input_data.pricing_model == PricingModel.VOLUME_DISCOUNT:
            if not input_data.tiers:
                raise ValueError("Volume discount pricing requires tiers")
            return self._calculate_volume_discount_price(input_data.base_price, input_data.quantity, input_data.tiers)
        
        elif input_data.pricing_model == PricingModel.SUBSCRIPTION:
            # Annual subscription discount (20% off for annual)
            months = Decimal("12.0")  # Assuming annual subscription
            monthly_price = input_data.base_price
            annual_price = monthly_price * months
            discount = annual_price * Decimal("0.20")  # 20% discount
            return annual_price - discount
        
        else:
            raise ValueError(f"Unsupported pricing model: {input_data.pricing_model}")
    
    def _calculate_tiered_price(self, base_price: Decimal, quantity: int, tiers: List[PriceTier]) -> Decimal:
        """Calculate price using tiered pricing model."""
        total_price = Decimal("0.00")
        remaining_quantity = quantity
        
        for tier in sorted(tiers, key=lambda x: x.min_quantity):
            if remaining_quantity <= 0:
                break
            
            tier_quantity = self._get_tier_quantity(remaining_quantity, tier)
            if tier_quantity > 0:
                total_price += tier.unit_price * Decimal(str(tier_quantity))
                remaining_quantity -= tier_quantity
        
        return total_price
    
    def _calculate_volume_discount_price(self, base_price: Decimal, quantity: int, tiers: List[PriceTier]) -> Decimal:
        """Calculate price using volume discount pricing model."""
        applicable_tier = None
        
        for tier in sorted(tiers, key=lambda x: x.min_quantity, reverse=True):
            if quantity >= tier.min_quantity:
                applicable_tier = tier
                break
        
        if applicable_tier is None:
            # Use base price if no tier matches
            return base_price * Decimal(str(quantity))
        
        return applicable_tier.unit_price * Decimal(str(quantity))
    
    def _get_tier_quantity(self, remaining_quantity: int, tier: PriceTier) -> int:
        """Get the quantity that falls within a specific tier."""
        if tier.max_quantity is None:
            return remaining_quantity
        
        tier_capacity = tier.max_quantity - tier.min_quantity + 1
        return min(remaining_quantity, tier_capacity)
    
    def _apply_discounts(self, subtotal: Decimal, discounts: List[Discount]) -> Tuple[Decimal, List[Dict]]:
        """Apply all applicable discounts to the subtotal."""
        total_discount = Decimal("0.00")
        applied_discounts = []
        
        for discount in discounts:
            if discount.min_purchase is not None and subtotal < discount.min_purchase:
                continue
            
            if discount.discount_type == DiscountType.PERCENTAGE:
                discount_amount = subtotal * (discount.value / Decimal("100.0"))
            elif discount.discount_type == DiscountType.FIXED_AMOUNT:
                discount_amount = discount.value
            elif discount.discount_type == DiscountType.BUY_X_GET_Y:
                # For simplicity, assume buy 1 get 1 free
                discount_amount = subtotal / Decimal("2.0")
            else:
                continue
            
            # Apply max discount limit if specified
            if discount.max_discount is not None:
                discount_amount = min(discount_amount, discount.max_discount)
            
            # Ensure discount doesn't make price negative
            discount_amount = min(discount_amount, subtotal - total_discount)
            
            if discount_amount > Decimal("0.00"):
                total_discount += discount_amount
                applied_discounts.append({
                    "type": discount.discount_type.value,
                    "amount": float(discount_amount),
                    "code": discount.code
                })
        
        return total_discount, applied_discounts
    
    def _apply_taxes(self, amount: Decimal, taxes: List[Tax]) -> Tuple[Decimal, List[Dict]]:
        """Apply all applicable taxes to the amount."""
        total_tax = Decimal("0.00")
        applied_taxes = []
        
        for tax in taxes:
            tax_amount = amount * (tax.rate / Decimal("100.0"))
            total_tax += tax_amount
            applied_taxes.append({
                "type": tax.tax_type.value,
                "rate": float(tax.rate),
                "jurisdiction": tax.jurisdiction,
                "amount": float(tax_amount)
            })
        
        return total_tax, applied_taxes
    
    def _round_currency(self, amount: Decimal) -> Decimal:
        """Round currency amount to 2 decimal places using banking rounding."""
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    
    def get_calculation_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent calculation history."""
        return self._calculation_history[-limit:] if self._calculation_history else []
    
    def clear_history(self) -> None:
        """Clear calculation history."""
        self._calculation_history.clear()


# Convenience functions for common use cases
def calculate_simple_price(
    base_price: float,
    quantity: int,
    discount_percent: float = 0.0,
    tax_rate: float = 0.0
) -> Dict[str, float]:
    """
    Calculate price with simple per-unit pricing.
    
    Args:
        base_price: Price per unit
        quantity: Number of units
        discount_percent: Percentage discount (0-100)
        tax_rate: Tax rate percentage (0-100)
        
    Returns:
        Dictionary with price components
    """
    calculator = PricingCalculator()
    
    input_data = PricingInput(
        pricing_model=PricingModel.PER_UNIT,
        base_price=Decimal(str(base_price)),
        quantity=quantity,
        discounts=[Discount(
            discount_type=DiscountType.PERCENTAGE,
            value=Decimal(str(discount_percent))
        )] if discount_percent > 0 else None,
        taxes=[Tax(
            tax_type=TaxType.SALES_TAX,
            rate=Decimal(str(tax_rate)),
            jurisdiction="default"
        )] if tax_rate > 0 else None
    )
    
    return calculator.calculate_price(input_data)


def validate_pricing_input(input_dict: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[PricingInput]]:
    """
    Validate pricing input dictionary and return validation result.
    
    Args:
        input_dict: Dictionary containing pricing input
        
    Returns:
        Tuple of (is_valid, error_message, validated_input)
    """
    try:
        validated_input = PricingInput(**input_dict)
        return True, None, validated_input
    except ValidationError as e:
        error_msg = "; ".join([f"{err['loc'][0]}: {err['msg']}" for err in e.errors()])
        return False, error_msg, None
    except Exception as e:
        return False, str(e), None