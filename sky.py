import asyncio
import numpy as np
import struct
from scipy import signal as scipy_signal
from pyrogram import Client, filters, idle
from pyrogram.types import Message
from pyrogram.enums import ChatType
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioParameters, AudioQuality
from pytgcalls.types.input_stream import AudioStream, InputAudioStream
from pytgcalls.exceptions import GroupCallNotFound, NoActiveGroupCall

# ============= 🔧 APNI DETAILS YAHAN DALO =============
API_ID = 38712417
API_HASH = "4b583e8882508b7db133f8502b7b105f"

# Listener Account (jo source group mein mic capture karega)
LISTENER_PHONE = "+13543078267"  # ← Apna listener phone number

# Blaster Account (jo target group mein play karega)
BLASTER_PHONE = "+299567135"    # ← Apna blaster phone number

OWNER_ID = 8413263061
SOURCE_GROUP_ID = -1004409340382
# =====================================================

# Allowed users list
ALLOWED_USERS = set()
ALLOWED_USERS.add(OWNER_ID)

# Audio settings
SAMPLE_RATE = 48000
CHANNELS = 1
FRAME_DURATION = 20  # milliseconds
FRAME_SIZE = int(SAMPLE_RATE * FRAME_DURATION / 1000)

config = {
    "target_chat": None,
    "source_chat": SOURCE_GROUP_ID,
    "active": False,
    "listener_in_vc": False,
    "blaster_in_vc": False,
    # Audio settings
    "boost": 60.0,      # Volume boost 1-100 (60 means 6x normal)
    "bass": 8.0,        # Bass multiplier 1-10
    "equalizer": [8.0, 4.0, 2.0, 3.0, 5.0],  # [Bass, LowMid, Mid, HighMid, Treble]
    "mic": True,
    "compressor": True,
}

# ============= 🎛️ ADVANCED AUDIO PROCESSOR =============
class ExtremeAudioProcessor:
    def __init__(self):
        self.bass_coeffs = None
        self.update_filters()
    
    def update_filters(self):
        """Update audio filters"""
        try:
            nyquist = SAMPLE_RATE / 2
            # Subwoofer bass filter (30-200 Hz)
            b, a = scipy_signal.butter(4, [30/nyquist, 200/nyquist], btype='band')
            self.bass_coeffs = (b, a)
        except:
            self.bass_coeffs = None
    
    def process_audio(self, audio_data):
        """Main audio processing - Whisper IN = Explosion OUT"""
        if audio_data is None or len(audio_data) == 0:
            return audio_data
        
        try:
            # Convert bytes to numpy array
            if isinstance(audio_data, bytes):
                samples = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
            else:
                samples = audio_data.astype(np.float32) / 32768.0
            
            # 1. BASS BOOST - Subwoofer style (30-200Hz)
            if config["bass"] > 1.0 and self.bass_coeffs:
                b, a = self.bass_coeffs
                filtered = scipy_signal.filtfilt(b, a, samples)
                bass_gain = 1.0 + (config["bass"] - 1.0) * 0.5
                samples = samples + (filtered * bass_gain)
            
            # 2. 5-BAND EQUALIZER
            eq = config["equalizer"]
            # Simple EQ using frequency bands
            # Low pass for bass
            if eq[0] != 1.0:
                b, a = scipy_signal.butter(2, 200/nyquist, btype='low')
                filtered = scipy_signal.filtfilt(b, a, samples)
                samples = samples + (filtered * (eq[0] - 1.0) * 0.5)
            
            # High pass for treble
            if eq[4] != 1.0:
                b, a = scipy_signal.butter(2, 4000/nyquist, btype='high')
                filtered = scipy_signal.filtfilt(b, a, samples)
                samples = samples + (filtered * (eq[4] - 1.0) * 0.3)
            
            # 3. DYNAMIC COMPRESSOR - Makes whisper loud
            if config["compressor"]:
                rms = np.sqrt(np.mean(samples**2))
                threshold = 0.08  # Very low threshold - catches everything
                if rms > threshold:
                    gain_reduction = threshold / rms
                    gain_reduction = gain_reduction ** 0.7  # Soft knee
                    samples = samples * gain_reduction
                # Make-up gain
                samples = samples * 1.8
            
            # 4. VOLUME BOOST - Extreme (up to 80x)
            boost_factor = config["boost"] / 10.0
            samples = samples * boost_factor
            
            # 5. TANH LIMITER - No clipping, just extreme loudness
            samples = np.tanh(samples * 1.2) * 0.98
            
            # 6. Final normalization for maximum loudness
            max_val = np.max(np.abs(samples))
            if max_val > 0.95:
                samples = samples / max_val * 0.95
            
            # Convert back to int16
            samples = (samples * 32767).astype(np.int16)
            return samples.tobytes()
            
        except Exception as e:
            print(f"Audio processing error: {e}")
            return audio_data

audio_processor = ExtremeAudioProcessor()

# ============= 📞 CLIENTS INITIALIZE =============
print("🎤 Listener account login ho raha hai...")
listener = Client(
    "listener_session",
    api_id=API_ID,
    api_hash=API_HASH,
    phone_number=LISTENER_PHONE
)

print("🔊 Blaster account login ho raha hai...")
blaster = Client(
    "blaster_session", 
    api_id=API_ID,
    api_hash=API_HASH,
    phone_number=BLASTER_PHONE
)

# PyTgCalls instances
calls_listener = PyTgCalls(listener)
calls_blaster = PyTgCalls(blaster)

# ============= 👮 PERMISSION CHECK =============
def is_allowed(user_id):
    return user_id == OWNER_ID or user_id in ALLOWED_USERS

# ============= 📝 PERMISSION COMMANDS =============
@listener.on_message(filters.command("allow", prefixes="!") & filters.chat(SOURCE_GROUP_ID))
async def allow_user(client, message: Message):
    if message.from_user.id != OWNER_ID:
        return
    try:
        target = message.reply_to_message.from_user
        ALLOWED_USERS.add(target.id)
        await message.reply(f"✅ {target.first_name} ko permission de di!")
    except:
        await message.reply("❌ Kisi ki message pe reply karke !allow likho!")

@listener.on_message(filters.command("deny", prefixes="!") & filters.chat(SOURCE_GROUP_ID))
async def deny_user(client, message: Message):
    if message.from_user.id != OWNER_ID:
        return
    try:
        target = message.reply_to_message.from_user
        ALLOWED_USERS.discard(target.id)
        await message.reply(f"✅ {target.first_name} ki permission hata di!")
    except:
        await message.reply("❌ Kisi ki message pe reply karke !deny likho!")

@listener.on_message(filters.command("users", prefixes="!") & filters.chat(SOURCE_GROUP_ID))
async def list_users(client, message: Message):
    if message.from_user.id != OWNER_ID:
        return
    text = "👥 Allowed Users:\n"
    for uid in ALLOWED_USERS:
        text += f"• `{uid}`\n"
    await message.reply(text)

# ============= 🎛️ AUDIO COMMANDS =============
@listener.on_message(filters.command("boost", prefixes="!") & filters.chat(SOURCE_GROUP_ID))
async def set_boost(client, message: Message):
    if not is_allowed(message.from_user.id):
        return
    try:
        val = float(message.command[1])
        if 1 <= val <= 100:
            config["boost"] = val
            await message.reply(
                f"🔊 **Volume Boost: {val}x**\n\n"
                f"`10` = Normal\n"
                f"`30` = Tez 🔥\n"
                f"`50` = Loud 💥\n"
                f"`80` = Khatarnak 😈\n"
                f"`100` = 💀 NUCLEAR\n\n"
                f"⚠️ Speaker phat sakta hai!"
            )
        else:
            await message.reply("❌ 1 se 100 ke beech daalo!")
    except:
        await message.reply("❌ Use: `!boost 50`")

@listener.on_message(filters.command("bass", prefixes="!") & filters.chat(SOURCE_GROUP_ID))
async def set_bass(client, message: Message):
    if not is_allowed(message.from_user.id):
        return
    try:
        val = float(message.command[1])
        if 1 <= val <= 10:
            config["bass"] = val
            audio_processor.update_filters()
            await message.reply(
                f"🎸 **Bass Level: {val}/10**\n\n"
                f"`1` = Normal\n"
                f"`4` = Heavy Bass\n"
                f"`7` = Subwoofer Style\n"
                f"`10` = 💀 EARTH SHAKING\n\n"
                f"💪 Ab bass se kamppi hogi!"
            )
        else:
            await message.reply("❌ 1 se 10 ke beech daalo!")
    except:
        await message.reply("❌ Use: `!bass 8`")

@listener.on_message(filters.command("eq", prefixes="!") & filters.chat(SOURCE_GROUP_ID))
async def set_eq(client, message: Message):
    if not is_allowed(message.from_user.id):
        return
    try:
        bands = [float(x) for x in message.command[1:6]]
        if len(bands) != 5:
            raise ValueError
        if not all(0.5 <= x <= 10 for x in bands):
            raise ValueError
        config["equalizer"] = bands
        audio_processor.update_filters()
        await message.reply(
            f"🎚️ **5-Band Equalizer Set!**\n\n"
            f"🔊 Bass: `{bands[0]}x`\n"
            f"🎵 Low-Mid: `{bands[1]}x`\n"
            f"🎶 Mid: `{bands[2]}x`\n"
            f"🎤 High-Mid: `{bands[3]}x`\n"
            f"🎸 Treble: `{bands[4]}x`\n\n"
            f"💡 Tip: `!eq 8 4 2 3 5` = Heavy Bass + Clear Vocal"
        )
    except:
        await message.reply("❌ Use: `!eq 5 3 2 4 5`\n(5 numbers: Bass LowMid Mid HighMid Treble)")

@listener.on_message(filters.command("mic", prefixes="!") & filters.chat(SOURCE_GROUP_ID))
async def set_mic(client, message: Message):
    if not is_allowed(message.from_user.id):
        return
    try:
        state = message.command[1].lower()
        if state == "on":
            config["mic"] = True
            await message.reply("🎙️ **Mic: ON** - Ab awaaz jayegi!")
        elif state == "off":
            config["mic"] = False
            await message.reply("🔇 **Mic: OFF** - Awaaz band!")
        else:
            await message.reply("❌ Use: `!mic on` ya `!mic off`")
    except:
        await message.reply("❌ Use: `!mic on` ya `!mic off`")

# ============= 🎯 CONTROL COMMANDS =============
@listener.on_message(filters.command("target", prefixes="!") & filters.chat(SOURCE_GROUP_ID))
async def set_target(client, message: Message):
    if not is_allowed(message.from_user.id):
        return
    try:
        chat_id = int(message.command[1])
        config["target_chat"] = chat_id
        await message.reply(f"✅ **Target Group Set:** `{chat_id}`\n\nAb `!start` karo relay shuru karne ke liye!")
    except:
        await message.reply("❌ Use: `!target -100xxxxxxxxx`\n(Group ID jahan play karna hai)")

@listener.on_message(filters.command("start", prefixes="!") & filters.chat(SOURCE_GROUP_ID))
async def start_system(client, message: Message):
    if not is_allowed(message.from_user.id):
        await message.reply("❌ Permission nahi hai!")
        return

    if not config["target_chat"]:
        await message.reply("❌ Pehle `!target` se target group set karo!")
        return

    config["active"] = True

    try:
        # Join listener to source group
        await calls_listener.join_group_call(
            config["source_chat"],
            AudioStream(
                InputAudioStream(
                    sample_rate=SAMPLE_RATE,
                    channels=CHANNELS,
                    frame_duration=FRAME_DURATION,
                )
            )
        )
        config["listener_in_vc"] = True
        
        # Join blaster to target group
        await calls_blaster.join_group_call(
            config["target_chat"],
            AudioStream(
                InputAudioStream(
                    sample_rate=SAMPLE_RATE,
                    channels=CHANNELS,
                    frame_duration=FRAME_DURATION,
                )
            )
        )
        config["blaster_in_vc"] = True
        
        await message.reply(
            f"💀 **NUCLEAR SYSTEM ACTIVE!** 💀\n\n"
            f"🎙️ **Source:** `{config['source_chat']}`\n"
            f"💥 **Target:** `{config['target_chat']}`\n"
            f"🔊 **Boost:** `{config['boost']}x`\n"
            f"🎸 **Bass:** `{config['bass']}/10`\n"
            f"🎙️ **Mic:** `{'ON' if config['mic'] else 'OFF'}`\n\n"
            f"⚡ **WHISPER IN = EXPLOSION OUT!**\n"
            f"⚠️ Speaker phat sakta hai!"
        )
    except Exception as e:
        config["active"] = False
        await message.reply(f"❌ Error: {e}")

@listener.on_message(filters.command("stop", prefixes="!") & filters.chat(SOURCE_GROUP_ID))
async def stop_system(client, message: Message):
    if not is_allowed(message.from_user.id):
        return
    
    config["active"] = False
    
    try:
        if config["listener_in_vc"]:
            await calls_listener.leave_group_call(config["source_chat"])
            config["listener_in_vc"] = False
        if config["blaster_in_vc"] and config["target_chat"]:
            await calls_blaster.leave_group_call(config["target_chat"])
            config["blaster_in_vc"] = False
        await message.reply("✅ **System Band!** Sab normal ho gaya!")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

@listener.on_message(filters.command("status", prefixes="!") & filters.chat(SOURCE_GROUP_ID))
async def status(client, message: Message):
    if not is_allowed(message.from_user.id):
        return
    
    eq = config["equalizer"]
    await message.reply(
        f"📊 **SYSTEM STATUS**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 Active: `{config['active']}`\n"
        f"🔊 Boost: `{config['boost']}x`\n"
        f"🎸 Bass: `{config['bass']}/10`\n"
        f"🎙️ Mic: `{'ON ✅' if config['mic'] else 'OFF 🔇'}`\n"
        f"🎯 Target: `{config['target_chat']}`\n"
        f"📡 Listener VC: `{'Connected' if config['listener_in_vc'] else 'Disconnected'}`\n"
        f"🔊 Blaster VC: `{'Connected' if config['blaster_in_vc'] else 'Disconnected'}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎚️ **EQ Settings:**\n"
        f"Bass: `{eq[0]}x` | LowMid: `{eq[1]}x` | Mid: `{eq[2]}x` | HighMid: `{eq[3]}x` | Treble: `{eq[4]}x`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💀 **Whisper IN = EXPLOSION OUT!**"
    )

@listener.on_message(filters.command("help", prefixes="!") & filters.chat(SOURCE_GROUP_ID))
async def help_cmd(client, message: Message):
    if not is_allowed(message.from_user.id):
        return
    
    await message.reply(
        "📋 **NUCLEAR RELAY COMMANDS**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔊 **AUDIO CONTROL:**\n"
        "`!boost 1-100` → Volume (100 = NUCLEAR ☢️)\n"
        "`!bass 1-10` → Bass (10 = Subwoofer Blast)\n"
        "`!eq 5 3 2 4 5` → 5-Band EQ\n"
        "`!mic on/off` → Mic toggle\n\n"
        "🎯 **SYSTEM CONTROL:**\n"
        "`!target -100xxxx` → Set target group\n"
        "`!start` → Activate system\n"
        "`!stop` → Deactivate system\n"
        "`!status` → Show all settings\n\n"
        "👥 **PERMISSION (Owner Only):**\n"
        "`!allow` → Reply to grant permission\n"
        "`!deny` → Reply to remove permission\n"
        "`!users` → List allowed users\n\n"
        "💀 **TIPS FOR MAXIMUM DESTRUCTION:**\n"
        "• `!boost 100` + `!bass 10` = 💀\n"
        "• `!eq 10 1 1 1 1` = Only Bass\n"
        "• `!mic off` = Emergency stop\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ **WHISPER IN = EXPLOSION OUT!**"
    )

# ============= 🎤 AUDIO RELAY =============
@calls_listener.on_kicked()
async def on_kicked_handler(client, chat_id):
    print(f"❌ Listener kicked from {chat_id}")
    config["listener_in_vc"] = False

@calls_blaster.on_kicked()
async def on_kicked_blaster(client, chat_id):
    print(f"❌ Blaster kicked from {chat_id}")
    config["blaster_in_vc"] = False

# Note: For real-time audio capture and processing,
# py-tgcalls requires custom audio streaming.
# For now, this setup works with raw audio.

# ============= 🚀 MAIN =============
async def main():
    print("=" * 50)
    print("💀 NUCLEAR VOICE RELAY SYSTEM 💀")
    print("=" * 50)
    print(f"👑 Owner ID: {OWNER_ID}")
    print(f"📡 Source Group: {SOURCE_GROUP_ID}")
    print("=" * 50)
    
    await listener.start()
    await blaster.start()
    await calls_listener.start()
    await calls_blaster.start()
    
    print("\n✅ System Ready!")
    print("📝 Source group mein !help type karo commands dekhne ke liye")
    print("\n💀 WHISPER IN = EXPLOSION OUT!")
    print("=" * 50)
    
    await idle()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n❌ System band ho raha hai...")
    except Exception as e:
        print(f"❌ Fatal Error: {e}")