#!/usr/bin/env python3
"""
Minimal RGB Matrix Test
This will help us diagnose exactly where the problem is.
"""
import sys
import time

print("="*60)
print("RGB Matrix Minimal Test")
print("="*60)
print()

# Test 1: Can we import the module?
print("Test 1: Importing rgbmatrix module...")
try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions
    print("✓ SUCCESS: Module imported")
except ImportError as e:
    print(f"✗ FAILED: {e}")
    print("Install with: cd ~/rpi-rgb-led-matrix && sudo make install-python PYTHON=$(which python3)")
    sys.exit(1)
except Exception as e:
    print(f"✗ FAILED: {e}")
    sys.exit(1)

print()

# Test 2: Can we create options?
print("Test 2: Creating RGBMatrixOptions...")
try:
    options = RGBMatrixOptions()
    print("✓ SUCCESS: Options object created")
except Exception as e:
    print(f"✗ FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()

# Test 3: Set basic options
print("Test 3: Configuring options...")
try:
    options.rows = 16
    options.cols = 192
    options.brightness = 100
    options.hardware_mapping = 'adafruit-hat'
    options.gpio_slowdown = 4
    options.pwm_bits = 11
    options.drop_privileges = False
    print("✓ SUCCESS: Options configured")
    print(f"  Rows: {options.rows}")
    print(f"  Cols: {options.cols}")
    print(f"  Hardware: {options.hardware_mapping}")
except Exception as e:
    print(f"✗ FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()

# Test 4: Try to create the matrix (this is where it might hang)
print("Test 4: Creating RGBMatrix object...")
print("NOTE: This might hang if hardware is misconfigured.")
print("If this hangs, press Ctrl+C and check:")
print("  - Is the Adafruit HAT properly seated on GPIO pins?")
print("  - Is the ribbon cable connected to the panel?")
print("  - Is the panel powered (5V)?")
print()
print("Attempting to create matrix...")
sys.stdout.flush()

try:
    matrix = RGBMatrix(options=options)
    print("✓ SUCCESS: Matrix object created!")
except Exception as e:
    print(f"✗ FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()

# Test 5: Create canvas
print("Test 5: Creating frame canvas...")
try:
    canvas = matrix.CreateFrameCanvas()
    print("✓ SUCCESS: Canvas created")
except Exception as e:
    print(f"✗ FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()

# Test 6: Draw something simple
print("Test 6: Drawing test pattern...")
try:
    # Fill with red
    for x in range(192):
        for y in range(16):
            canvas.SetPixel(x, y, 255, 0, 0)
    
    print("✓ SUCCESS: Drew red pattern")
    
    # Swap to display
    canvas = matrix.SwapOnVSync(canvas)
    print("✓ SUCCESS: Swapped canvas to display")
    print()
    print("If you see a RED screen on your panel, hardware is working!")
    print("Waiting 3 seconds...")
    time.sleep(3)
    
    # Clear it
    for x in range(192):
        for y in range(16):
            canvas.SetPixel(x, y, 0, 0, 0)
    canvas = matrix.SwapOnVSync(canvas)
    print("✓ SUCCESS: Cleared display")
    
except Exception as e:
    print(f"✗ FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()
print("="*60)
print("ALL TESTS PASSED!")
print("="*60)
print()
print("Your RGB Matrix hardware is working correctly.")
print("The problem might be in how the ticker initializes it.")
print()
print("Next steps:")
print("1. If you saw a red flash on the panel, hardware is good")
print("2. Run the ticker and share the FULL output including where it stops")
print("3. We can adjust the initialization parameters")
