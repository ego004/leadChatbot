# Test to verify ServiceManager singleton behavior
from app.services.service_manager import service_manager

# Test 1: Same instance across imports
def test_singleton():
    # Import again to simulate multiple imports
    from app.services.service_manager import service_manager as sm2
    
    print(f"service_manager id: {id(service_manager)}")
    print(f"sm2 id: {id(sm2)}")
    print(f"Are they the same instance? {service_manager is sm2}")

if __name__ == "__main__":
    test_singleton()
