import os
import shutil

AUDIO_EXTS = {'.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a'}
VIDEO_EXTS = {'.mp4', '.mkv', '.avi', '.mov', '.webm'}


def which_ffmpeg(packaged_path=None):
    """Return the path to ffmpeg if found in PATH or packaged folder."""
    exe = shutil.which('ffmpeg')
    if exe:
        return exe
    if packaged_path:
        ffmpeg_local = os.path.join(packaged_path, 'ffmpeg', 'bin', 'ffmpeg.exe')
        if os.path.exists(ffmpeg_local):
            return ffmpeg_local
    return None
