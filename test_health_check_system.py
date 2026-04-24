#!/usr/bin/env python3
"""
Test the infrastructure-grade health check system.

This script tests:
1. Health check manager initialization
2. Liveness probe responses
3. Readiness probe responses
4. Configuration error handling
5. Exchange status tracking
"""

import sys
import os

# Add bot directory to path
bot_path = os.path.join(os.path.dirname(__file__), 'bot')
if bot_path not in sys.path:
    sys.path.insert(0, bot_path)

# Import directly from health_check module
from health_check import get_health_manager, ReadinessStatus
import json


def test_health_manager_initialization():
    """Test that health manager initializes correctly"""
    print("=" * 70)
    print("TEST 1: Health Manager Initialization")
    print("=" * 70)
    
    manager = get_health_manager()
    assert manager is not None, "Health manager should not be None"
    assert manager.state.is_alive, "Process should be marked as alive"
    assert not manager.state.is_ready, "Process should not be ready initially"
    
    print("✅ Health manager initialized correctly")
    print()


def test_liveness_probe():
    """Test liveness probe always returns alive status"""
    print("=" * 70)
    print("TEST 2: Liveness Probe")
    print("=" * 70)
    
    manager = get_health_manager()
    
    # Get liveness status
    status = manager.get_liveness_status()
    
    print("Liveness status:")
    print(json.dumps(status, indent=2))
    
    assert status['status'] == 'alive', "Status should be 'alive'"
    assert 'uptime_seconds' in status, "Should include uptime"
    assert 'timestamp' in status, "Should include timestamp"
    
    print("✅ Liveness probe working correctly")
    print()


def test_readiness_probe_not_ready():
    """Test readiness probe when service is not ready"""
    print("=" * 70)
    print("TEST 3: Readiness Probe - Not Ready")
    print("=" * 70)
    
    manager = get_health_manager()
    
    # Get readiness status (should not be ready initially)
    status, http_code = manager.get_readiness_status()
    
    print("Readiness status:")
    print(json.dumps(status, indent=2))
    print(f"HTTP Status Code: {http_code}")
    
    assert http_code == 503, f"Should return 503, got {http_code}"
    assert not status['ready'], "Should not be ready"
    
    print("✅ Readiness probe correctly indicates not ready")
    print()


def test_configuration_error():
    """Test configuration error handling"""
    print("=" * 70)
    print("TEST 4: Configuration Error Handling")
    print("=" * 70)
    
    manager = get_health_manager()
    
    # Mark a configuration error
    error_msg = "No exchange credentials configured"
    manager.mark_configuration_error(error_msg)
    
    # Check state
    assert not manager.state.configuration_valid, "Config should be invalid"
    assert manager.state.readiness_status == ReadinessStatus.CONFIGURATION_ERROR.value
    assert error_msg in manager.state.configuration_errors, "Error should be tracked"
    
    # Get readiness status
    status, http_code = manager.get_readiness_status()
    
    print("Readiness status with configuration error:")
    print(json.dumps(status, indent=2))
    print(f"HTTP Status Code: {http_code}")
    
    assert http_code == 503, f"Should return 503 for config error, got {http_code}"
    assert status['status'] == ReadinessStatus.CONFIGURATION_ERROR.value
    assert 'configuration_errors' in status, "Should include error list"
    
    print("✅ Configuration errors handled correctly")
    print()


def test_exchange_status_tracking():
    """Test exchange status tracking"""
    print("=" * 70)
    print("TEST 5: Exchange Status Tracking")
    print("=" * 70)
    
    # Get a fresh instance for this test
    from health_check import HealthCheckManager
    manager = HealthCheckManager()
    
    # Mark configuration as valid
    manager.mark_configuration_valid()
    
    # Update exchange status - no exchanges connected
    manager.update_exchange_status(connected=0, expected=2)
    status, http_code = manager.get_readiness_status()
    
    print("Status with 0/2 exchanges:")
    print(json.dumps(status, indent=2))
    assert not status['ready'], "Should not be ready with no exchanges"
    assert status['exchanges']['connected'] == 0
    assert status['exchanges']['expected'] == 2
    
    # Update exchange status - some exchanges connected
    manager.update_exchange_status(connected=1, expected=2)
    status, http_code = manager.get_readiness_status()
    
    print("\nStatus with 1/2 exchanges:")
    print(json.dumps(status, indent=2))
    assert status['ready'], "Should be ready with at least one exchange"
    assert status['exchanges']['connected'] == 1
    assert http_code == 200, "Should return 200 when ready"
    
    print("✅ Exchange status tracking works correctly")
    print()


def test_detailed_status():
    """Test detailed status endpoint"""
    print("=" * 70)
    print("TEST 6: Detailed Status")
    print("=" * 70)
    
    manager = get_health_manager()
    
    # Get detailed status
    status = manager.get_detailed_status()
    
    print("Detailed status:")
    print(json.dumps(status, indent=2))
    
    assert 'service' in status, "Should include service name"
    assert 'version' in status, "Should include version"
    assert 'liveness' in status, "Should include liveness info"
    assert 'readiness' in status, "Should include readiness info"
    assert 'operational_state' in status, "Should include operational state"
    
    print("✅ Detailed status includes all required information")
    print()


def test_heartbeat_updates():
    """Test heartbeat updates"""
    print("=" * 70)
    print("TEST 7: Heartbeat Updates")
    print("=" * 70)
    
    manager = get_health_manager()
    
    # Get initial heartbeat
    initial_status = manager.get_liveness_status()
    initial_heartbeat = manager.state.last_heartbeat
    
    print(f"Initial heartbeat: {initial_heartbeat}")
    
    # Wait a moment and update heartbeat
    import time
    time.sleep(0.1)
    manager.heartbeat()
    
    # Check heartbeat updated
    updated_heartbeat = manager.state.last_heartbeat
    print(f"Updated heartbeat: {updated_heartbeat}")
    
    assert updated_heartbeat > initial_heartbeat, "Heartbeat should be updated"
    
    print("✅ Heartbeat updates working correctly")
    print()


def main():
    """Run all tests"""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 15 + "HEALTH CHECK SYSTEM TEST SUITE" + " " * 23 + "║")
    print("╚" + "=" * 68 + "╝")
    print()
    
    try:
        test_health_manager_initialization()
        test_liveness_probe()
        test_readiness_probe_not_ready()
        test_configuration_error()
        test_exchange_status_tracking()
        test_detailed_status()
        test_heartbeat_updates()
        
        print("=" * 70)
        print("✅ ALL TESTS PASSED")
        print("=" * 70)
        print()
        print("The health check system is working correctly:")
        print("  ✅ Liveness probes always return 'alive' when process is running")
        print("  ✅ Readiness probes correctly indicate service readiness")
        print("  ✅ Configuration errors are tracked and reported")
        print("  ✅ Exchange connection status is monitored")
        print("  ✅ Detailed status provides operational visibility")
        print()
        
        return 0
        
    except AssertionError as e:
        print()
        print("=" * 70)
        print("❌ TEST FAILED")
        print("=" * 70)
        print(f"Error: {e}")
        print()
        return 1
    except Exception as e:
        print()
        print("=" * 70)
        print("❌ UNEXPECTED ERROR")
        print("=" * 70)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        print()
        return 1


if __name__ == '__main__':
    sys.exit(main())
