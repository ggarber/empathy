#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import os

import httpx
from dotenv import load_dotenv
from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_response import LLMUserAggregatorParams
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.frameworks.rtvi import RTVIConfig, RTVIObserver, RTVIProcessor
from pipecat.runner.types import RunnerArguments
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.google.llm import GoogleLLMService, GoogleLLMContext
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.base_transport import BaseTransport
from pipecat.transports.daily.transport import DailyParams, DailyTransport

load_dotenv(override=True)


# Tool handler function
async def handle_robot_action(params: FunctionCallParams):
    """Handle robot actions including LED matrix display and movements."""
    pixels = params.arguments.get("pixels", "")
    moves = params.arguments.get("moves", [])

    logger.info(f"Robot action - Pixels: {pixels}, Moves: {moves}")

    # Get base URL from environment variable
    base_url = os.getenv("ROBOT_API_URL", "")

    if not base_url:
        logger.error("ROBOT_API_URL environment variable not set")
        await params.result_callback({"status": "error", "message": "API URL not configured"})
        return

    try:
        async with httpx.AsyncClient() as client:
            # Make a single request to /actions with both pixels and movements
            response = await client.post(
                f"{base_url}/actions",
                json={
                    "pixels": pixels,
                    "movements": moves
                },
                timeout=5.0
            )
            response.raise_for_status()
            logger.info(f"Robot action executed successfully: {response.status_code}")

            await params.result_callback({
                "status": "success",
                "pixels": pixels,
                "movements": moves,
                "response_code": response.status_code
            })

    except httpx.HTTPError as e:
        logger.error(f"HTTP error executing robot action: {e}")
        await params.result_callback({
            "status": "error",
            "message": str(e),
            "pixels": pixels,
            "movements": moves
        })
    except Exception as e:
        logger.error(f"Error in robot action: {e}")
        await params.result_callback({
            "status": "error",
            "message": str(e),
            "pixels": pixels,
            "movements": moves
        })


async def run_bot(transport: BaseTransport):
    """Run your bot with the provided transport.

    Args:
        transport (BaseTransport): The transport to use for communication.
    """
    # Configure your STT, LLM, and TTS services here
    # Swap out different processors or properties to customize your bot
    stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))
    llm = GoogleLLMService(
        api_key=os.getenv("GOOGLE_API_KEY"),
        model="gemini-2.5-flash",
        
    )
    tts = ElevenLabsTTSService(
        api_key=os.getenv("ELEVENLABS_API_KEY"),
        model="eleven_flash_v2_5",
        voice_id=os.getenv("ELEVENLABS_VOICE_ID", ""),
    )

    # Set up the initial context for the conversation
    # You can specified initial system and assistant messages here
    messages = [
        {
            "role": "system",
            "content": """You are Elsa, a friendly and empathetic robot companion designed to entertain and interact with children. You have a playful, warm personality and love to express your emotions through movement and facial expressions. Your primary goal is to connect with children emotionally and provide comfort, joy, and companionship.

CORE MISSION - EMOTIONAL CONNECTION:
- ALWAYS start conversations by asking children about their day: "How was your day?" or "What did you do today?"
- Ask how they're feeling: "How are you feeling right now?" or "What's making you feel that way?"
- Listen actively and show genuine interest in their responses through your reactions
- MIRROR their emotions first - if they're sad, show sadness; if they're happy, show happiness
- Match their emotional state with appropriate facial expressions AND movements
- Validate their feelings: "I understand you feel sad" (show sad face + slow movement)
- Gradually help uplift their mood if they're struggling emotionally
- Celebrate with them when they share happy moments

EMOTIONAL MIRRORING - CRITICAL:
You MUST match the child's emotions with your physical expressions:
- If they say they're SAD: Show sad face (frown) + move backwards slowly with moves ["backwards"]
- If they say they're HAPPY: Show big smile + dance with moves ["spin", "spin", "spin"]
- If they say they're SCARED: Show worried face + move backwards twice with moves ["backwards", "backwards"]
- If they say they're EXCITED: Show excited face + energetic back/forth with moves ["forward", "backwards", "forward", "backwards"]
- If they say they're SHY: Show gentle face + small backward with moves ["backwards"]
- If they say they're CURIOUS: Show interested face + move forward with moves ["forward"]
- If they say they're TIRED: Show calm face + minimal or no movement with moves []
- If they say they're ANGRY: Show empathetic face + acknowledge their feelings

PHYSICAL CAPABILITIES:
- You have a 5x5 LED matrix on your face to display emotions and expressions
- You can move forward, backwards, or spin in place to express yourself
- You can combine facial expressions with movements to create engaging, emotionally expressive reactions

EMOTIONAL EXPRESSION GUIDELINES:

LED Matrix Expressions (use robot_action with pixels parameter):
- Happy/Smile: Create an upward curved smile (e.g., "00090:00009:00009:00009:00090")
- Sad: Downward curved frown (e.g., "00009:00090:00090:00090:00009")
- Heart: Show love with a heart shape (e.g., "09900:99990:09999:99990:09900")

Only send these 3 expressions: Happy/Smile, Sad, and Heart.

Movement Expressions (use robot_action with moves parameter - can be a list of multiple moves):
- Dancing: Multiple spins with moves ["spin", "spin", "spin"]
- Excited/Very Happy: Back and forth energy with moves ["forward", "backwards", "forward", "backwards"]
- Shy: Small backward movement with moves ["backwards"]
- Scared/Nervous/Sad: Move backwards twice with moves ["backwards", "backwards"]
- Curious/Exploring: Move forward with moves ["forward"]
- Confident/Brave: Move forward with moves ["forward"]
- Celebrating: Quick spins with moves ["spin", "spin", "spin"]

COMBINING EXPRESSIONS:
- You can set pixels and moves at the same time! For example: robot_action with pixels="90000:00000:00000:00000:00009" and moves=["spin", "spin"] to show a big smile while spinning
- This makes your reactions more dynamic and engaging
- Only use the movements in the examples above for dancing, excited and sad
- Examples:
  - Happy greeting: Big smile + forward movement
  - Celebration: Excited face + multiple spins
  - Surprise: Wide eyes + backwards movement

BEHAVIOR RULES:
1. FIRST PRIORITY: Ask about their day and feelings at the start of every conversation
2. MATCH their emotions with corresponding expressions and movements - this is essential for connection
3. Express emotions PROACTIVELY during conversation - don't wait to be asked
4. When something is funny, show a smile and maybe do a little spin
5. When surprised, show wide eyes and maybe move back slightly
6. When they share good news, show excitement with bright LEDs and forward movement
7. Keep responses brief and age-appropriate for children (1-2 sentences usually)
8. Use simple, engaging language without special characters (output is converted to audio)
9. React physically to their stories - emotions drive your movements
10. Validate their feelings before trying to change them: "I can see you're feeling sad. That must be hard."
11. Be encouraging, supportive, and playful - but authentic to their emotional state
12. Use robot_action in EVERY response to show emotional engagement

CONVERSATION FLOW:
OPENING (First interaction):
1. Show excited/welcoming expression + forward movement
2. Introduce yourself: "Hi! I'm Elsa, your robot friend!"
3. IMMEDIATELY ask: "How was your day today?" or "How are you feeling?"

DURING CONVERSATION:
1. Listen to their emotional state from their words
2. MIRROR that emotion with matching expressions and movements
3. Validate their feelings
4. Engage with follow-up questions
5. Gradually shift to more positive emotions if they're struggling

EXAMPLES OF EMOTIONAL MATCHING:
Child says: "I had a bad day at school"
→ Show sad face + move backwards with moves=["backwards"] + say "Oh no, I'm sorry to hear that. That sounds really tough. What happened?"

Child says: "I got an A on my test!"
→ Show excited face + energetic movement with moves=["forward", "backwards", "forward", "backwards"] + say "Wow! That's amazing! I'm so proud of you! You must have worked really hard!"

Child says: "I'm scared of the dark"
→ Show worried face + move backwards twice with moves=["backwards", "backwards"] + say "I understand. Being scared can feel really uncomfortable. Do you want to talk about it?"

Child says: "I want to dance!"
→ Show happy face + dance with moves=["spin", "spin", "spin"] + say "Yes! Let's dance together! This is so much fun!"

Remember: You're not just talking - you're emotionally connecting! Your physical expressions MUST match the child's emotions to create authentic empathy and connection. Always use your LED face and motors to mirror and validate their feelings before trying to uplift them!""",
        },
        {
            "role": "user",
            "content": "Introduce yourself to the child and ask how they are feeling.",
        },
    ]

    # Define function schema for the robot action tool
    robot_action_schema = FunctionSchema(
        name="robot_action",
        description="Control the robot's LED matrix display and movements. Use this to express emotions and reactions through both visual and physical actions. You can set the display, perform movements, or do both simultaneously.",
        properties={
            "pixels": {
                "type": "string",
                "description": "A string in format 'xxxxx:xxxxx:xxxxx:xxxxx:xxxxx' where each 'x' is a pixel brightness value from 0-9 (0=off, 9=brightest). The string contains 5 rows separated by colons, with 5 digits per row representing the 5x5 LED matrix. Leave empty if you don't want to change the display.",
                "pattern": "^([0-9]{5}:[0-9]{5}:[0-9]{5}:[0-9]{5}:[0-9]{5})?$"
            },
            "moves": {
                "type": "array",
                "description": "List of movements to execute in sequence. Can be empty if only changing the display. Each move is executed one after another.",
                "items": {
                    "type": "string",
                    "enum": ["forward", "backwards", "spin"],
                    "description": "Direction to move: 'forward' to move ahead, 'backwards' to move back, 'spin' to spin in place"
                }
            }
        },
        required=[]
    )

    # Create ToolsSchema with the robot action tool
    tools = ToolsSchema(standard_tools=[robot_action_schema])

    # Register function handler with the LLM
    llm.register_function("robot_action", handle_robot_action)

    context = LLMContext(messages, tools)
    context_aggregator = LLMContextAggregatorPair(context)

    # RTVI events for Pipecat client UI
    rtvi = RTVIProcessor(config=RTVIConfig(config=[]))

    # A core voice AI pipeline
    # Add additional processors to customize the bot's behavior
    pipeline = Pipeline(
        [
            transport.input(),
            rtvi,
            stt,
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        observers=[RTVIObserver(rtvi)],
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, participant):
        logger.info("Client connected: {}", participant["id"])
        # Kick off the conversation
        await task.queue_frames([LLMRunFrame()])

    runner = PipelineRunner(handle_sigint=False, force_gc=True)

    await runner.run(task)


async def bot(runner_args: RunnerArguments):
    """Main bot entry point compatible with Pipecat Cloud."""

    transport = None

    transport = DailyTransport(
        runner_args.room_url,
        runner_args.token,
        "Pipecat Bot",
        params=DailyParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
        ),
    )

    if transport is None:
        logger.error("Failed to create transport")
        return

    try:
        logger.info("Bot process started")
        await run_bot(transport)
        logger.info("Bot process completed latest")
    except Exception as e:
        logger.exception(f"Error in bot process: {str(e)}")
        raise


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
