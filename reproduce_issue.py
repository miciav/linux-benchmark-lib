from lb_controller.services.plugin_service import create_registry
import logging

# Configure logging to see output
logging.basicConfig(level=logging.INFO)

print("First creation:")
r1 = create_registry()
print(f"R1: {id(r1)}")

print("Second creation:")
r2 = create_registry()
print(f"R2: {id(r2)}")

assert r1 is r2
