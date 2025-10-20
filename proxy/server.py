from flask import Flask, request, jsonify
import logging
import time
from comm.HubClient import ConnectionState, HubClient
from data.HubMonitor import HubMonitor
from utils.setup import setup_logging
import os
import re
from enum import Enum

# Commands doc
# https://gist.github.com/bricklife/13c7fe07c3145dd94f4f23d20ccf5a79?permalink_comment_id=4234638


# Setup logging
log_level = logging.INFO
setup_logging(os.path.dirname(__file__) + "/logs/server.log", log_level)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Initialize HubClient
client = HubClient()
hm = HubMonitor(client)
client.start()

# Motor configuration constants
MOTOR_LEFT_PORT = 'A'
MOTOR_RIGHT_PORT = 'E'
MOTOR_TIME_MS = 1000  # 3 seconds

# Movement enum
class Movement(Enum):
    FORWARD = 'forward'
    BACKWARDS = 'backwards'
    SPIN = 'spin'

# Sound enum
class Sound(Enum):
    HAPPY = 'happy'
    SAD = 'sad'
    CURIOUS = 'curious'

# Sound patterns: list of (note, duration) tuples
# MIDI note values: C4=60, D4=62, E4=64, F4=65, G4=67, A4=69, B4=71, C5=72
SOUND_PATTERNS = {
    Sound.HAPPY: [
        (60, 200),  # C4
        (64, 200),  # E4
        (67, 200),  # G4
        (72, 400),  # C5 - longer final note
    ],
    Sound.SAD: [
        (64, 300),  # E4
        (62, 300),  # D4
        (60, 300),  # C4
        (57, 400),  # A3 - longer final note
    ],
    Sound.CURIOUS: [
        (60, 150),  # C4
        (65, 150),  # F4
        (60, 150),  # C4
        (69, 300),  # A4 - questioning tone
    ],
}

SOUND_VOLUME = 10  # Default volume

# Helper functions to eliminate code duplication
def validate_image_format(image_str):
    """
    Validate image format: xxxxx:xxxxx:xxxxx:xxxxx:xxxxx
    where x is pixel brightness in range 0-9
    """
    pattern = r'^[0-9]{5}:[0-9]{5}:[0-9]{5}:[0-9]{5}:[0-9]{5}$'
    return re.match(pattern, image_str) is not None

def wait_for_hub_connection(timeout=10):
    """
    Wait for hub to connect with timeout
    Returns (success: bool, error_response: tuple or None)
    """
    start_time = time.time()
    while client.state is not ConnectionState.TELEMETRY:
        if time.time() - start_time > timeout:
            return False, (jsonify({'error': 'Hub not connected (timeout)'}), 503)
        logger.info('Waiting for hub to connect...')
        time.sleep(0.2)
    return True, None

def handle_pixels_action(pixels):
    """
    Handle pixels/matrix display action or text display
    If the string contains ':', it's treated as a pixel matrix
    Otherwise, it's treated as text to display
    Returns (response_dict, status_code)
    """
    if not isinstance(pixels, str):
        return {'error': '"pixels" must be a string'}, 400

    # Check if it's a pixel matrix (contains ':') or text
    if ':' in pixels:
        # Pixel matrix mode
        # Validate format
        if not validate_image_format(pixels):
            return {
                'error': 'Invalid format. Expected: xxxxx:xxxxx:xxxxx:xxxxx:xxxxx where x is 0-9'
            }, 400

        # Send image to hub
        logger.info(f'Sending image to hub: {pixels}')
        result = client.send_message('scratch.display_image', {'image': pixels})

        return {
            'status': 'success',
            'message': 'Image sent to hub',
            'image': pixels,
            'result': result
        }, 200
    else:
        # Text mode
        logger.info(f'Sending text to hub: {pixels}')
        result = client.send_message('scratch.display_text', {'text': pixels})

        return {
            'status': 'success',
            'message': 'Text sent to hub',
            'text': pixels,
            'result': result
        }, 200

def execute_single_movement(movement_str):
    """
    Execute a single movement
    Returns (response_dict, status_code)
    """
    # Validate movement value
    movement_str = movement_str.lower()
    valid_movements = [m.value for m in Movement]
    if movement_str not in valid_movements:
        return {
            'error': f'Invalid movement. Expected one of: {", ".join(valid_movements)}'
        }, 400

    # Determine motor speeds based on movement type
    if movement_str == Movement.FORWARD.value:
        left_speed = -75
        right_speed = 75
        move_both_motors = True
    elif movement_str == Movement.BACKWARDS.value:
        left_speed = 75
        right_speed = -75
        move_both_motors = True
    elif movement_str == Movement.SPIN.value:
        left_speed = 75  # 4x faster than 75
        right_speed = None
        move_both_motors = False

    # Send motor start commands
    logger.info(f'Executing movement: {movement_str}')

    # Start left motor
    start_result_left = client.send_message('scratch.motor_start', {
        'port': MOTOR_LEFT_PORT,
        'speed': left_speed,
        'stall': True
    })

    # Start right motor for forward/backwards
    start_result_right = None
    if move_both_motors:
        start_result_right = client.send_message('scratch.motor_start', {
            'port': MOTOR_RIGHT_PORT,
            'speed': right_speed,
            'stall': True
        })

    # Sleep for the motor duration (convert ms to seconds)
    time.sleep(MOTOR_TIME_MS / 1000.0)

    # Stop left motor
    stop_result_left = client.send_message('scratch.motor_stop', {
        'port': MOTOR_LEFT_PORT,
        'stop': 1
    })

    # Stop right motor for forward/backwards
    stop_result_right = None
    if move_both_motors:
        stop_result_right = client.send_message('scratch.motor_stop', {
            'port': MOTOR_RIGHT_PORT,
            'stop': 1
        })

    # Build response
    response = {
        'status': 'success',
        'message': f'Movement command sent: {movement_str}',
        'movement': movement_str,
        'motors': {
            'left': {'port': MOTOR_LEFT_PORT, 'speed': left_speed}
        },
        'results': {
            'start': {'left': start_result_left},
            'stop': {'left': stop_result_left}
        }
    }

    if move_both_motors:
        response['motors']['right'] = {'port': MOTOR_RIGHT_PORT, 'speed': right_speed}
        response['results']['start']['right'] = start_result_right
        response['results']['stop']['right'] = stop_result_right

    return response, 200

def handle_movements_action(movements_data):
    """
    Handle movement action - accepts either a single movement string or a list of movements
    Executes movements sequentially if a list is provided
    Returns (response_dict, status_code)
    """
    # Handle single string
    if isinstance(movements_data, str):
        return execute_single_movement(movements_data)

    # Handle list of movements
    if isinstance(movements_data, list):
        # Validate all movements are strings
        for idx, movement in enumerate(movements_data):
            if not isinstance(movement, str):
                return {'error': f'"movements" at index {idx} must be a string'}, 400

        # Execute movements sequentially
        movements_results = []
        for movement in movements_data:
            result, status_code = execute_single_movement(movement)
            if status_code != 200:
                # If any movement fails, return the error
                return result, status_code
            movements_results.append(result)

        # Return combined response
        return {
            'status': 'success',
            'message': f'{len(movements_results)} movements executed sequentially',
            'movements': movements_results
        }, 200

    # Invalid type
    return {'error': '"movement" must be a string or a list of strings'}, 400

@app.route('/matrix', methods=['POST'])
def matrix():
    """
    POST endpoint that receives a JSON with a 'pixels' field

    Two modes supported:
    1. Pixel matrix: String format xxxxx:xxxxx:xxxxx:xxxxx:xxxxx (contains ':')
       where x is the pixel brightness in range 0-9
    2. Text: Any string without ':' will be displayed as scrolling text

    Examples:
    - {"pixels": "09990:90090:90090:90090:09990"}  # Shows a square
    - {"pixels": "Hello World"}  # Shows scrolling text
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400

        if 'pixels' not in data:
            return jsonify({'error': 'Missing "pixels" field'}), 400

        # Wait for hub to connect
        success, error_response = wait_for_hub_connection()
        if not success:
            return error_response

        # Handle pixels action
        response, status_code = handle_pixels_action(data['pixels'])
        return jsonify(response), status_code

    except Exception as e:
        logger.error(f'Error processing request: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/move', methods=['POST'])
def move():
    """
    POST endpoint that receives a JSON with a 'movement' field
    containing either a single movement string or a list of movements

    Single movement: 'forward', 'backwards', or 'spin'
    List of movements: ['forward', 'spin', 'backwards']

    Movements in a list are executed sequentially.
    Controls motors on ports A (left) and E (right)
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400

        if 'movement' not in data:
            return jsonify({'error': 'Missing "movement" field'}), 400

        # Wait for hub to connect
        success, error_response = wait_for_hub_connection()
        if not success:
            return error_response

        # Handle movement action
        response, status_code = handle_movement_action(data['movement'])
        return jsonify(response), status_code

    except Exception as e:
        logger.error(f'Error processing request: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/actions', methods=['POST'])
def actions():
    """
    POST endpoint that receives a JSON with optional 'pixels' and/or 'movement' fields
    Allows combining both actions in a single request

    Request format:
    {
        "pixels": "xxxxx:xxxxx:xxxxx:xxxxx:xxxxx" | "Hello",  # optional
        "movement": "forward" | ["forward", "spin"]  # optional - string or list
    }

    The 'pixels' field supports two modes:
    - Pixel matrix: "xxxxx:xxxxx:xxxxx:xxxxx:xxxxx" (contains ':')
    - Text: "Hello World" (no ':' - displays as scrolling text)

    The 'movement' field can be:
    - A single movement string: "forward", "backwards", or "spin"
    - A list of movements: ["forward", "spin", "backwards"] (executed sequentially)

    At least one field must be provided.
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400

        # Check that at least one action is provided
        has_pixels = 'pixels' in data
        has_movements = 'movements' in data

        if not has_pixels and not has_movements:
            return jsonify({
                'error': 'At least one of "pixels" or "movements" must be provided'
            }), 400

        # Wait for hub to connect
        success, error_response = wait_for_hub_connection()
        if not success:
            return error_response

        # Process actions and collect results
        response = {
            'status': 'success',
            'message': 'Actions executed',
            'actions': {}
        }

        # Handle pixels action if provided
        if has_pixels:
            pixels_response, pixels_status = handle_pixels_action(data['pixels'])
            if pixels_status != 200:
                # If pixels action failed, return error
                return jsonify(pixels_response), pixels_status
            response['actions']['pixels'] = pixels_response

        # Handle movement action if provided
        if has_movements:
            movements_responses, movements_statuses = handle_movements_action(data['movements'])
            if movements_statuses != 200:
                # If movements action failed, return error
                return jsonify(movements_responses), movements_statuses
            response['actions']['movements'] = movements_responses

        return jsonify(response), 200

    except Exception as e:
        logger.error(f'Error processing request: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/sound', methods=['POST'])
def sound():
    """
    POST endpoint that receives a JSON with an 'emotion' field
    containing one of: 'happy', 'sad', or 'curious'
    Plays a sequence of beeps using scratch.sound_beep_for_time
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400

        if 'emotion' not in data:
            return jsonify({'error': 'Missing "emotion" field'}), 400

        emotion_str = data['emotion']

        if not isinstance(emotion_str, str):
            return jsonify({'error': '"emotion" must be a string'}), 400

        # Validate emotion value
        emotion_str = emotion_str.lower()
        valid_emotions = [s.value for s in Sound]
        if emotion_str not in valid_emotions:
            return jsonify({
                'error': f'Invalid emotion. Expected one of: {", ".join(valid_emotions)}'
            }), 400

        # Wait for hub to connect
        timeout = 10  # seconds
        start_time = time.time()
        while client.state is not ConnectionState.TELEMETRY:
            if time.time() - start_time > timeout:
                return jsonify({'error': 'Hub not connected (timeout)'}), 503
            logger.info('Waiting for hub to connect...')
            time.sleep(0.2)

        # Get the sound pattern for this emotion
        emotion_enum = Sound(emotion_str)
        pattern = SOUND_PATTERNS[emotion_enum]

        # Send beep commands for each note in the pattern
        logger.info(f'Playing sound pattern: {emotion_str}')
        results = []

        for note, duration in pattern:
            result = client.send_message('scratch.sound_beep_for_time', {
                'duration': duration,
                'note': note,
                'volume': SOUND_VOLUME
            })
            results.append({
                'note': note,
                'duration': duration,
                'result': result
            })
            # Small delay between notes for clarity
            time.sleep(duration / 1000.0)

        return jsonify({
            'status': 'success',
            'message': f'Sound pattern played: {emotion_str}',
            'emotion': emotion_str,
            'pattern': [{'note': n, 'duration': d} for n, d in pattern],
            'results': results
        }), 200

    except Exception as e:
        logger.error(f'Error processing request: {str(e)}')
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
