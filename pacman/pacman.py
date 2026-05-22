#!/usr/bin/env python

from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics



#from samplebase import SampleBase

import time
import math
import colorsys
from PIL import Image






options = RGBMatrixOptions()
options.rows = 16
options.cols = 16
options.chain_length = 10
options.gpio_slowdown = 2
options.brightness = 30

matrix = RGBMatrix(options = options)
def clearMatrix():
    for x in range(matrix.width):
        for y in range( matrix.height):
            double_buffer.SetPixel(x, y, 0,0,0)
from PIL import Image
import time

# Define constants
MATRIX_WIDTH = 160
MATRIX_HEIGHT = 16
SPRITE_WIDTH = 16  # Assuming each sprite is 16 pixels wide
PACMAN_WIDTH = 16  # Assuming Pacman is also 16 pixels wide
GAP = 8  # Gap between ghosts
INITIAL_PACMAN_GAP = 80  # Initial gap between Pacman and the first ghost
FINAL_PACMAN_GAP = -SPRITE_WIDTH  # Final gap where ghosts overlap Pacman
ANIMATION_DELAY = 0.03  # Delay between frames in seconds
PACMAN_DIES_LOCATION = 130 
PACMAN_DIES_DELAY = 0.07  # Delay between frames in the Pacman death animation

# Load sprite images
ghostRed1 = Image.open('ghostRed1.ppm').convert('RGB')
ghostRed2 = Image.open('ghostRed2.ppm').convert('RGB')
ghostPink1 = Image.open('ghostPink1.ppm').convert('RGB')
ghostPink2 = Image.open('ghostPink2.ppm').convert('RGB')
ghostLightBlue1 = Image.open('ghostLightBlue1.ppm').convert('RGB')
ghostLightBlue2 = Image.open('ghostLightBlue2.ppm').convert('RGB')
ghostOrange1 = Image.open('ghostOrange1.ppm').convert('RGB')
ghostOrange2 = Image.open('ghostOrange2.ppm').convert('RGB')

# Load Pacman images
pacman1 = Image.open('pacman1.ppm').convert('RGB')
pacman2 = Image.open('pacman2.ppm').convert('RGB')
pacman3 = Image.open('pacman3.ppm').convert('RGB')

# Load PacmanDies images
pacmanDies = [
    Image.open(f'pacmanDies{i+1}.ppm').convert('RGB') for i in range(11)
]

# Initialize double buffer and matrix
double_buffer = matrix.CreateFrameCanvas()

# List of sprites, their positions, and individual frame counters
sprites = [
    {'images': [pacman1, pacman2, pacman3], 'x': -PACMAN_WIDTH, 'frame': 0, 'switch_rate': 4},
    {'images': [ghostRed1, ghostRed2], 'x': -PACMAN_WIDTH - INITIAL_PACMAN_GAP - SPRITE_WIDTH, 'frame': 0, 'switch_rate': 5},
    {'images': [ghostPink1, ghostPink2], 'x': -PACMAN_WIDTH - INITIAL_PACMAN_GAP - 2*(SPRITE_WIDTH + GAP), 'frame': 0, 'switch_rate': 7},
    {'images': [ghostLightBlue1, ghostLightBlue2], 'x': -PACMAN_WIDTH - INITIAL_PACMAN_GAP - 3*(SPRITE_WIDTH + GAP), 'frame': 0, 'switch_rate': 9},
    {'images': [ghostOrange1, ghostOrange2], 'x': -PACMAN_WIDTH - INITIAL_PACMAN_GAP - 4*(SPRITE_WIDTH + GAP), 'frame': 0, 'switch_rate': 11}
]

# Function to play the Pacman death animation
def play_pacman_dies(x_position):
    for image in pacmanDies:
        double_buffer.Clear()
        double_buffer.SetImage(image, x_position)
        matrix.SwapOnVSync(double_buffer)
        time.sleep(PACMAN_DIES_DELAY)

# Main animation loop
while True:
    double_buffer.Clear()

    # Calculate the current gap between Pacman and the first ghost based on Pacman's position
    pacman_position = sprites[0]['x']
    if pacman_position < PACMAN_DIES_LOCATION:
        # Linearly decrease the gap as Pacman approaches 2/3 of the way across the matrix
        current_gap = INITIAL_PACMAN_GAP - (INITIAL_PACMAN_GAP - FINAL_PACMAN_GAP) * (pacman_position / PACMAN_DIES_LOCATION)
    else:
        # Once Pacman is beyond 2/3, the gap is at its minimum (overlap)
        current_gap = FINAL_PACMAN_GAP

    # Update positions of the ghosts based on the current gap
    sprites[1]['x'] = sprites[0]['x'] - current_gap - SPRITE_WIDTH
    sprites[2]['x'] = sprites[1]['x'] - (SPRITE_WIDTH + GAP)
    sprites[3]['x'] = sprites[2]['x'] - (SPRITE_WIDTH + GAP)
    sprites[4]['x'] = sprites[3]['x'] - (SPRITE_WIDTH + GAP)

    # Check if the red ghost catches up to Pacman
    if sprites[1]['x'] >= pacman_position - 2:
        play_pacman_dies(pacman_position)
        break

    for sprite in sprites:
        # Update the frame counter for each sprite
        sprite['frame'] += 1
        
        # Switch between the two images for ghosts or three images for Pacman based on the individual sprite's frame counter
        image = sprite['images'][(sprite['frame'] // sprite['switch_rate']) % len(sprite['images'])]
        
        # Draw the sprite at the current position
        double_buffer.SetImage(image, sprite['x'])
        
        # Move sprite to the right
        sprite['x'] += 1
        
        # Reset sprite position when it moves out of the right side of the matrix
        if sprite['x'] > MATRIX_WIDTH:
            # Reset positions, with Pacman leading and ghosts following with the initial gap
            sprite['x'] = -PACMAN_WIDTH - INITIAL_PACMAN_GAP - (SPRITE_WIDTH + GAP) * (sprites.index(sprite) - 1)
        
    # Swap the buffers to display the new frame
    matrix.SwapOnVSync(double_buffer)
    
    # Wait before the next frame
    time.sleep(ANIMATION_DELAY)
