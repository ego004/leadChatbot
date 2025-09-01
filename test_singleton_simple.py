#!/usr/bin/env python3
"""Simple test for ServiceManager singleton without heavy dependencies"""

# Test the singleton pattern directly
import sys
import os
sys.path.insert(0, '.')

class MockGeminiService:
    def __init__(self):
        print("MockGeminiService initialized")

class MockVectorStoreService:
    def __init__(self, collection_name):
        self.collection_name = collection_name
        print(f"MockVectorStoreService initialized for {collection_name}")

# Monkey patch to avoid dependencies
sys.modules['app.services.gemini_service'] = type('MockModule', (), {'GeminiService': MockGeminiService})()
sys.modules['app.services.vector_store_service'] = type('MockModule', (), {'VectorStoreService': MockVectorStoreService})()
sys.modules['app.services.lead_service'] = type('MockModule', (), {'LeadService': lambda db: None})()

# Now test the ServiceManager
from app.services.service_manager import ServiceManager

def test_singleton():
    print("=== Testing ServiceManager Singleton Pattern ===")
    
    # Create multiple instances
    sm1 = ServiceManager()
    sm2 = ServiceManager()
    sm3 = ServiceManager()
    
    print(f"Instance 1 ID: {id(sm1)}")
    print(f"Instance 2 ID: {id(sm2)}")
    print(f"Instance 3 ID: {id(sm3)}")
    
    # Check if they're the same instance
    same_instance = sm1 is sm2 is sm3
    print(f"All same instance? {same_instance}")
    
    if same_instance:
        print("✅ ServiceManager singleton working correctly")
    else:
        print("❌ ServiceManager singleton FAILED")
    
    return same_instance

def test_import_behavior():
    print("\n=== Testing Import Behavior ===")
    
    # Test importing service_manager multiple times
    from app.services.service_manager import service_manager as sm1
    print(f"First import ID: {id(sm1)}")
    
    # Import in different way
    import importlib
    sm_module = importlib.import_module('app.services.service_manager')
    sm2 = sm_module.service_manager
    print(f"Second import ID: {id(sm2)}")
    
    # Direct import again
    from app.services.service_manager import service_manager as sm3
    print(f"Third import ID: {id(sm3)}")
    
    same_instance = sm1 is sm2 is sm3
    print(f"All imports same instance? {same_instance}")
    
    if same_instance:
        print("✅ Import behavior working correctly")
    else:
        print("❌ Import behavior FAILED")
    
    return same_instance

if __name__ == "__main__":
    test1 = test_singleton()
    test2 = test_import_behavior()
    
    if test1 and test2:
        print("\n🎉 All ServiceManager singleton tests PASSED")
    else:
        print("\n💥 ServiceManager singleton tests FAILED")
