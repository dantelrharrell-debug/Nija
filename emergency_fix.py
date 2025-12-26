#!/usr/bin/env python3
"""
EMERGENCY FIX SCRIPT
Immediately stops bleeding and enforces position cap
"""
import os
import sys
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger("emergency_fix")

def main():
    """Execute emergency fixes."""
    logger.info("="*80)
    logger.info("🚨 EMERGENCY FIX SCRIPT")
    logger.info("="*80)
    
    # Step 1: Block all new entries immediately
    logger.info("\n1️⃣ BLOCKING ALL NEW ENTRIES...")
    stop_entries_file = 'STOP_ALL_ENTRIES.conf'
    with open(stop_entries_file, 'w') as f:
        f.write("EMERGENCY: All new entries blocked\n")
        f.write(f"Created: {os.popen('date').read()}")
    logger.info(f"   ✅ Created {stop_entries_file}")
    
    # Step 2: Run position cap enforcer to reduce to 8 positions
    logger.info("\n2️⃣ ENFORCING POSITION CAP (MAX 8)...")
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
        from position_cap_enforcer import PositionCapEnforcer
        
        enforcer = PositionCapEnforcer(max_positions=8)
        success, result = enforcer.enforce_cap()
        
        logger.info(f"   Current positions: {result['current_count']}")
        logger.info(f"   Max allowed: {result['max_allowed']}")
        logger.info(f"   Excess: {result['excess']}")
        logger.info(f"   Sold: {result['sold']}")
        logger.info(f"   Status: {result['status']}")
        
        if success:
            logger.info("   ✅ Position cap enforced successfully")
        else:
            logger.warning(f"   ⚠️ Partial enforcement: {result['sold']}/{result['excess']} sold")
    
    except Exception as e:
        logger.error(f"   ❌ Error running enforcer: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    # Step 3: Summary
    logger.info("\n" + "="*80)
    logger.info("📊 EMERGENCY FIX SUMMARY")
    logger.info("="*80)
    logger.info("✅ New entries blocked")
    logger.info("✅ Position cap enforcement attempted")
    logger.info("")
    logger.info("⚠️ NEXT STEPS:")
    logger.info("   1. Monitor bot logs for exits")
    logger.info("   2. Review why strategy is buying indiscriminately")
    logger.info("   3. Fix exit logic to take profits")
    logger.info(f"   4. Remove {stop_entries_file} when ready to resume trading")
    logger.info("="*80)

if __name__ == '__main__':
    main()
