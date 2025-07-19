import csv
import os
import sys
from decimal import Decimal

# Add project root to path to allow imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from models.base import Base
from models.financing_rule import FinancingRule # We will create this model next
from config.config import Config

def main():
    if not Config.SQLALCHEMY_DATABASE_URI:
        print("ERROR: DATABASE_URL is not configured.")
        return

    engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
    Session = sessionmaker(bind=engine)
    session = Session()

    csv_file_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'fulgor cashea - Sheet1.csv')
    print(f"Reading Cashea rules from: {csv_file_path}")

    try:
        with open(csv_file_path, mode='r', encoding='utf-8') as infile:
            reader = csv.DictReader(infile)
            
            # Clear existing Cashea rules to avoid duplicates
            session.execute(text("DELETE FROM financing_rules WHERE provider = 'Cashea'"))
            
            for row in reader:
                level = row['Nivel cashea'].strip()
                initial_pct_str = row['Porcentaje inicial normal'].replace('%', '').strip()
                installments = int(row['Cuotas normales'].strip())
                discount_pct_str = row['porcentaje de descuento'].replace('%', '').strip()

                initial_pct = Decimal(initial_pct_str) / 100
                discount_pct = Decimal(discount_pct_str) / 100

                rule = FinancingRule(
                    provider='Cashea',
                    level_name=level,
                    initial_payment_percentage=initial_pct,
                    installments=installments,
                    provider_discount_percentage=discount_pct
                )
                session.add(rule)
                print(f"Staging rule for {level}...")

        session.commit()
        print("\nSuccessfully loaded all Cashea rules into the database.")
    except Exception as e:
        session.rollback()
        print(f"\nAn error occurred: {e}")
    finally:
        session.close()

if __name__ == '__main__':
    # We need a dummy model file for this script to run
    if not os.path.exists('models/financing_rule.py'):
        with open('models/financing_rule.py', 'w') as f:
            f.write("""
from sqlalchemy import Column, Integer, String, NUMERIC
from . import Base
class FinancingRule(Base):
    __tablename__ = 'financing_rules'
    id = Column(Integer, primary_key=True)
    provider = Column(String)
    level_name = Column(String)
    initial_payment_percentage = Column(NUMERIC)
    installments = Column(Integer)
    provider_discount_percentage = Column(NUMERIC)
""")
    main()