import os
import asyncio
import logging
import tempfile
import shutil
from datetime import datetime
from typing import Dict, List
from dotenv import load_dotenv
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot token from environment variable
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    raise ValueError("Please set TELEGRAM_BOT_TOKEN environment variable")

# Store user sessions
user_sessions: Dict[int, Dict] = {}

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_message = (
        f"👋 Hello {user.first_name}!\n\n"
        "🎬 I can download audio/video from various platforms.\n\n"
        "📝 **How to use:**\n"
        "1. Send me a link (YouTube, Instagram, TikTok, etc.)\n"
        "2. I'll show available formats\n"
        "3. Choose your preferred quality\n\n"
        "🔍 **Supported sites:** YouTube, Instagram, TikTok, Twitter, Facebook, and 1000+ more!\n\n"
        "⚙️ Commands:\n"
        "/start - Show this message\n"
        "/help - Get help\n"
        "/cancel - Cancel current operation"
    )
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

# Help command
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📚 **Help Guide**\n\n"
        "1. **Send a URL**: Just paste any supported video/audio link\n"
        "2. **Choose Format**: I'll show available formats\n"
        "3. **Select Quality**: Choose from the buttons\n\n"
        "⚠️ **Important Notes:**\n"
        "• Large files may take time to upload\n"
        "• Some sites have download restrictions\n"
        "• Maximum file size: 2GB (Telegram limit)\n\n"
        "❓ **Having issues?**\n"
        "• Make sure the link is accessible\n"
        "• Try different quality options\n"
        "• Some videos may be age-restricted"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

# Cancel command
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_sessions:
        del user_sessions[user_id]
    await update.message.reply_text("✅ Operation cancelled.")

# Handle URL messages
async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    user_id = update.effective_user.id
    
    # Validate URL
    if not (url.startswith('http://') or url.startswith('https://')):
        await update.message.reply_text("❌ Please send a valid URL starting with http:// or https://")
        return
    
    # Check if URL is from supported sites
    blacklisted_domains = ['porn', 'xxx', 'adult']  # Add more if needed
    if any(domain in url.lower() for domain in blacklisted_domains):
        await update.message.reply_text("❌ This content is not supported.")
        return
    
    try:
        # Show processing message
        processing_msg = await update.message.reply_text("🔍 Extracting video information...")
        
        # Extract video info using yt-dlp
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if not info:
                await processing_msg.edit_text("❌ Could not extract video information.")
                return
            
            # Store info in user session
            user_sessions[user_id] = {
                'url': url,
                'info': info,
                'last_message_id': processing_msg.message_id
            }
            
            # Get available formats
            formats = info.get('formats', [])
            
            if not formats:
                # If no formats, try to get audio only
                await show_audio_options(update, context, info)
                return
            
            # Prepare format options
            video_formats = []
            audio_formats = []
            
            for f in formats:
                format_id = f.get('format_id')
                ext = f.get('ext', 'unknown')
                filesize = f.get('filesize') or f.get('filesize_approx')
                
                # Skip problematic formats
                if not format_id or ext == 'unknown':
                    continue
                
                # Video formats
                if f.get('vcodec') != 'none':
                    height = f.get('height', 0)
                    fps = f.get('fps', 0)
                    quality = f"{height}p"
                    if fps and fps > 30:
                        quality += f"@{int(fps)}fps"
                    
                    # Get size in MB
                    size_mb = round(filesize / (1024 * 1024), 1) if filesize else '?'
                    
                    video_formats.append({
                        'id': format_id,
                        'quality': quality,
                        'ext': ext,
                        'size': size_mb,
                        'note': f.get('format_note', ''),
                        'vcodec': f.get('vcodec'),
                        'acodec': f.get('acodec')
                    })
                
                # Audio only formats
                elif f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                    abr = f.get('abr', 0)
                    audio_quality = f"{abr}kbps" if abr else "audio"
                    size_mb = round(filesize / (1024 * 1024), 1) if filesize else '?'
                    
                    audio_formats.append({
                        'id': format_id,
                        'quality': audio_quality,
                        'ext': ext,
                        'size': size_mb,
                        'acodec': f.get('acodec')
                    })
            
            # Remove duplicates and sort
            video_formats = sorted(
                list({v['id']: v for v in video_formats}.values()),
                key=lambda x: int(x['quality'].replace('p', '').split('@')[0]) if x['quality'].replace('p', '').split('@')[0].isdigit() else 0,
                reverse=True
            )
            
            audio_formats = sorted(
                list({a['id']: a for a in audio_formats}.values()),
                key=lambda x: int(x['quality'].replace('kbps', '')) if x['quality'].replace('kbps', '').isdigit() else 0,
                reverse=True
            )
            
            # Create keyboard
            keyboard = []
            
            # Add video options
            if video_formats:
                keyboard.append([InlineKeyboardButton("📹 Video Formats", callback_data='header_video')])
                for fmt in video_formats[:8]:  # Limit to 8 formats
                    text = f"🎬 {fmt['quality']} ({fmt['ext'].upper()})"
                    if fmt['size'] != '?':
                        text += f" [{fmt['size']}MB]"
                    keyboard.append([InlineKeyboardButton(text, callback_data=f"v_{fmt['id']}")])
            
            # Add audio options
            if audio_formats:
                keyboard.append([InlineKeyboardButton("🎵 Audio Only", callback_data='header_audio')])
                for fmt in audio_formats[:6]:  # Limit to 6 formats
                    text = f"🎵 {fmt['quality']} ({fmt['ext'].upper()})"
                    if fmt['size'] != '?':
                        text += f" [{fmt['size']}MB]"
                    keyboard.append([InlineKeyboardButton(text, callback_data=f"a_{fmt['id']}")])
            
            # Add cancel button
            keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel')])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Prepare message
            title = info.get('title', 'Unknown Title')[:100]
            duration = info.get('duration', 0)
            duration_str = f"{duration // 60}:{duration % 60:02d}" if duration else "Unknown"
            
            message = (
                f"🎬 **{title}**\n"
                f"⏱ Duration: {duration_str}\n"
                f"📊 Available formats:\n\n"
                f"👇 **Select a format:**"
            )
            
            await processing_msg.edit_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        if 'Private video' in error_msg:
            await update.message.reply_text("❌ This video is private.")
        elif 'Members only' in error_msg:
            await update.message.reply_text("❌ This video is for members only.")
        elif 'Content warning' in error_msg:
            await update.message.reply_text("❌ Age-restricted content. Please login on YouTube first.")
        else:
            await update.message.reply_text(f"❌ Error: {error_msg[:200]}")
    except Exception as e:
        logger.error(f"Error processing URL: {e}")
        await update.message.reply_text("❌ An error occurred while processing the URL.")

# Show audio options for audio-only content
async def show_audio_options(update: Update, context: ContextTypes.DEFAULT_TYPE, info: Dict):
    user_id = update.effective_user.id
    
    # Store basic info for audio download
    user_sessions[user_id] = {
        'url': info.get('webpage_url', ''),
        'info': info,
        'audio_only': True
    }
    
    # Create audio format options
    keyboard = [
        [InlineKeyboardButton("🎵 MP3 (Best Quality)", callback_data="audio_mp3_best")],
        [InlineKeyboardButton("🎵 MP3 (128kbps)", callback_data="audio_mp3_128")],
        [InlineKeyboardButton("🎵 MP3 (64kbps)", callback_data="audio_mp3_64")],
        [InlineKeyboardButton("🎵 M4A/AAC", callback_data="audio_m4a")],
        [InlineKeyboardButton("🎵 Opus", callback_data="audio_opus")],
        [InlineKeyboardButton("❌ Cancel", callback_data='cancel')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    title = info.get('title', 'Audio Content')[:100]
    message = f"🎵 **{title}**\n\nSelect audio format:"
    
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

# Handle button callbacks
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if data == 'cancel':
        if user_id in user_sessions:
            del user_sessions[user_id]
        await query.edit_message_text("✅ Operation cancelled.")
        return
    
    if user_id not in user_sessions:
        await query.edit_message_text("❌ Session expired. Please send the URL again.")
        return
    
    # Get user session
    session = user_sessions[user_id]
    url = session['url']
    info = session.get('info', {})
    
    # Create temp directory
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Update message to show processing
        await query.edit_message_text("⏬ Downloading... This may take a while.")
        
        ydl_opts = {
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'progress_hooks': [lambda d: None],
        }
        
        # Configure based on selection
        if data.startswith('v_'):
            # Video download
            format_id = data[2:]
            ydl_opts['format'] = format_id
        elif data.startswith('a_'):
            # Audio-only download from video
            format_id = data[2:]
            ydl_opts['format'] = format_id
        elif data == 'audio_mp3_best':
            # Convert to MP3 with best quality
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'prefer_ffmpeg': True,
            })
        elif data == 'audio_mp3_128':
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '128',
                }],
                'prefer_ffmpeg': True,
            })
        elif data == 'audio_mp3_64':
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '64',
                }],
                'prefer_ffmpeg': True,
            })
        elif data == 'audio_m4a':
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'm4a',
                }],
                'prefer_ffmpeg': True,
            })
        elif data == 'audio_opus':
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'opus',
                }],
                'prefer_ffmpeg': True,
            })
        
        # Download the file
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # Find downloaded file
        downloaded_files = []
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                if file.endswith(('.mp4', '.mkv', '.webm', '.mp3', '.m4a', '.opus', '.aac', '.flac', '.wav')):
                    downloaded_files.append(os.path.join(root, file))
        
        if not downloaded_files:
            await query.edit_message_text("❌ No file was downloaded.")
            return
        
        # Send the file to user
        for file_path in downloaded_files:
            file_size = os.path.getsize(file_path)
            
            # Check file size (Telegram limit: 2GB for premium, 50MB for free)
            if file_size > 50 * 1024 * 1024:  # 50MB limit for free users
                await query.edit_message_text(
                    f"⚠️ File too large ({file_size/(1024*1024):.1f}MB). "
                    f"Telegram limit is 50MB for free users.\n"
                    f"Try selecting a lower quality format."
                )
                continue
            
            # Determine file type
            ext = os.path.splitext(file_path)[1].lower()
            if ext in ['.mp3', '.m4a', '.opus', '.aac', '.flac', '.wav']:
                await context.bot.send_audio(
                    chat_id=query.message.chat_id,
                    audio=open(file_path, 'rb'),
                    caption=f"🎵 {os.path.basename(file_path)}",
                    title=info.get('title', 'Downloaded Audio')[:64],
                    performer=info.get('uploader', 'Unknown')[:64],
                    reply_to_message_id=query.message.message_id
                )
            else:
                await context.bot.send_video(
                    chat_id=query.message.chat_id,
                    video=open(file_path, 'rb'),
                    caption=f"🎬 {os.path.basename(file_path)}",
                    supports_streaming=True,
                    reply_to_message_id=query.message.message_id
                )
        
        # Clean up
        await query.edit_message_text("✅ Download complete!")
        
    except Exception as e:
        logger.error(f"Download error: {e}")
        await query.edit_message_text(f"❌ Download failed: {str(e)[:200]}")
    
    finally:
        # Clean up temp directory
        try:
            shutil.rmtree(temp_dir)
        except:
            pass
        
        # Clear user session
        if user_id in user_sessions:
            del user_sessions[user_id]

# Error handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ An unexpected error occurred. Please try again."
        )

# Main function
def main():
    # Create application
    application = Application.builder().token(TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the bot
    print("🤖 Bot is starting...")
    print("📡 Press Ctrl+C to stop")
    
    # For Render deployment
    port = int(os.environ.get('PORT', 10000))
    
    if 'RENDER' in os.environ:
        # Use webhook for Render
        webhook_url = os.environ.get('RENDER_EXTERNAL_URL')
        if webhook_url:
            application.run_webhook(
                listen="0.0.0.0",
                port=port,
                url_path=TOKEN,
                webhook_url=f"{webhook_url}/{TOKEN}"
            )
        else:
            application.run_polling()
    else:
        # Use polling for local development
        application.run_polling()

if __name__ == '__main__':
    main()