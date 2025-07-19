# namwoo_app/models/financing_rule.py

from sqlalchemy import Column, Integer, String, NUMERIC, UniqueConstraint
from . import Base

class FinancingRule(Base):
    """
    SQLAlchemy ORM model for the 'financing_rules' table.
    
    Stores the business rules for different financing providers like Cashea,
    including payment percentages, installment counts, and applicable discounts.
    """
    __tablename__ = 'financing_rules'

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # The name of the financing company, e.g., 'Cashea'
    provider = Column(String(50), nullable=False, index=True)
    
    # The specific tier or level name, e.g., 'Nivel 1'
    level_name = Column(String(50), nullable=False)
    
    # The percentage of the total price required as an initial payment (e.g., 0.60 for 60%)
    initial_payment_percentage = Column(NUMERIC(5, 4), nullable=False)
    
    # The number of payments after the initial one
    installments = Column(Integer, nullable=False)
    
    # An optional discount applied by the provider (e.g., 0.13 for 13%)
    provider_discount_percentage = Column(NUMERIC(5, 4), nullable=True)

    # Ensure that each level for a given provider is unique
    __table_args__ = (
        UniqueConstraint('provider', 'level_name', name='uq_provider_level'),
    )

    def __repr__(self):
        """Provides a developer-friendly representation of the object."""
        return (f"<FinancingRule(provider='{self.provider}', level='{self.level_name}', "
                f"initial_pct='{self.initial_payment_percentage}')>")