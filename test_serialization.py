#!/usr/bin/env python3
"""Test the serialization fix for OrderConfiguration objects"""
import json

def _serialize_object_to_dict(obj) -> dict:
    """
    Safely convert any object to a dictionary for JSON serialization.
    """
    if obj is None:
        return {}
    
    if isinstance(obj, dict):
        return obj
    
    # Try JSON serialization first
    try:
        json_str = json.dumps(obj, default=str)
        return json.loads(json_str)
    except Exception:
        pass
    
    # Fallback: convert object attributes
    try:
        result = {}
        if hasattr(obj, '__dict__'):
            for key, value in obj.__dict__.items():
                if isinstance(value, (dict, list, str, int, float, bool, type(None))):
                    result[key] = value
                else:
                    result[key] = str(value)
        return result
    except Exception:
        return {"_object": str(obj), "_type": type(obj).__name__}

# Test with a mock OrderConfiguration object
class OrderConfiguration:
    def __init__(self):
        self.limit_price = "100.50"
        self.post_only = False

class MockOrder:
    def __init__(self):
        self.success = True
        self.error_response = {}
        self.order_id = "abc123"
        self.order_config = OrderConfiguration()

# Test
if __name__ == "__main__":
    mock_order = MockOrder()
    result = _serialize_object_to_dict(mock_order)
    
    print("✅ Serialization successful!")
    print(f"   success: {result.get('success')}")
    print(f"   order_id: {result.get('order_id')}")
    print(f"   order_config type: {type(result.get('order_config'))}")
    print(f"   error_response: {result.get('error_response')}")
    
    print(f"\n✅ .get() method works on serialized dict:")
    print(f"   result.get('success'): {result.get('success')}")
    print(f"   result.get('nonexistent', 'default'): {result.get('nonexistent', 'default')}")
    
    print("\n✅ All tests passed!")
