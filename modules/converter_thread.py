import os
import re
import subprocess
from PyQt5.QtCore import QThread, pyqtSignal
from modules.utils import which_ffmpeg, AUDIO_EXTS, VIDEO_EXTS


class ConverterThread(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, str)
    log_signal = pyqtSignal(str)

    def __init__(self, ffmpeg_path, input_files, output_folder, output_format, custom_name, quality, enhancement_mode, keep_metadata, separate_stems):
        super().__init__()
        self.ffmpeg_path = ffmpeg_path
        self.input_files = list(input_files)
        self.output_folder = output_folder
        self.output_format = output_format
        self.custom_name = custom_name
        self.quality = quality
        self.enhancement_mode = enhancement_mode
        self.keep_metadata = keep_metadata
        self.separate_stems = separate_stems
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True

    def _genre_from_path(self, path):
        p = path.lower()
        if 'rock' in p:
            return 'rock'
        if 'edm' in p or 'electronic' in p:
            return 'edm'
        if 'chill' in p or 'lofi' in p or 'lo-fi' in p:
            return 'chill'
        if 'classical' in p or 'orchestra' in p:
            return 'classical'
        if 'jazz' in p:
            return 'jazz'
        return None

    def _af_for_profile(self, profile, genre_hint=None):
        # Build FFmpeg -af string based on profile (and optional genre_hint)
        parts = []
        p = profile.lower() if profile else ''
        if 'normalize' in p:
            parts.append('loudnorm')
        if 'bass' in p:
            parts.append('equalizer=f=100:width_type=h:width=200:g=4')
        if 'treble' in p:
            parts.append('equalizer=f=8000:width_type=h:width=2000:g=3')
        if 'vocal' in p or 'clarity' in p:
            parts.append('acompressor=threshold=-21dB:ratio=3:attack=200:release=1000')
        if 'rock' in p or (genre_hint == 'rock' and p == 'auto'):
            parts.extend([
                'loudnorm',
                'equalizer=f=100:width_type=h:width=200:g=4',
                'equalizer=f=1000:width_type=h:width=300:g=3',
                'equalizer=f=8000:width_type=h:width=2000:g=2',
                'acompressor=threshold=-18dB:ratio=3:attack=50:release=250'
            ])
        if 'edm' in p or (genre_hint == 'edm' and p == 'auto'):
            parts.extend([
                'loudnorm',
                'equalizer=f=60:width_type=h:width=120:g=5',
                'equalizer=f=1000:width_type=h:width=300:g=2',
                'equalizer=f=10000:width_type=h:width=2000:g=3',
                'acompressor=threshold=-18dB:ratio=4:attack=20:release=200'
            ])
        if 'chill' in p or (genre_hint == 'chill' and p == 'auto'):
            parts.extend(['loudnorm', 'equalizer=f=1000:width_type=h:width=400:g=3', 'afftdn'])
        if 'classical' in p or (genre_hint == 'classical' and p == 'auto'):
            parts.extend(['loudnorm', 'equalizer=f=200:width_type=h:width=300:g=2', 'afftdn'])
        # If user selected 'auto' we use the genre hint if none of the above matched
        if p == 'auto' and genre_hint and not parts:
            return self._af_for_profile(genre_hint, genre_hint=None)
        # Join with commas
        return ','.join(parts) if parts else None

    def _audio_bitrate_args(self, output_ext):
        # Map quality label to bitrate / codec args
        q = self.quality
        if output_ext == 'flac':
            return ['-c:a', 'flac']  # flac ignores -b:a
        if output_ext in ('wav',):
            return ['-c:a', 'pcm_s16le']
        if output_ext in ('mp3',):
            bitrate = '320k' if q == 'High' else '192k' if q == 'Medium' else '128k'
            return ['-c:a', 'libmp3lame', '-b:a', bitrate]
        if output_ext in ('aac','m4a','mp4',):
            bitrate = '320k' if q == 'High' else '192k' if q == 'Medium' else '128k'
            return ['-c:a', 'aac', '-b:a', bitrate]
        # Default
        bitrate = '320k' if q == 'High' else '192k' if q == 'Medium' else '128k'
        return ['-c:a', 'libmp3lame', '-b:a', bitrate]

    def run(self):
        try:
            for idx, input_file in enumerate(self.input_files):
                if self._stop_requested:
                    self.finished.emit(False, 'Conversion stopped by user')
                    return

                base_name = os.path.splitext(os.path.basename(input_file))[0]
                output_name = f"{self.custom_name}_{idx+1}" if self.custom_name else f"{base_name}_converted"
                output_file = os.path.join(self.output_folder, f"{output_name}.{self.output_format}")

                # Determine file type
                ext = os.path.splitext(input_file)[1].lower()
                is_audio_in = ext in AUDIO_EXTS
                is_video_in = ext in VIDEO_EXTS

                # Genre hint from path
                genre_hint = self._genre_from_path(input_file)

                # Build audio filter
                af = self._af_for_profile(self.enhancement_mode, genre_hint=genre_hint)

                # Build base command
                cmd = [self.ffmpeg_path, '-y', '-i', input_file]

                # Map metadata
                if self.keep_metadata:
                    cmd += ['-map_metadata', '0']

                # For audio-only outputs
                out_ext_lower = self.output_format.lower()
                if out_ext_lower in AUDIO_EXTS:
                    # Audio output: drop video stream
                    cmd += ['-vn']
                    cmd += self._audio_bitrate_args(out_ext_lower)
                    if af:
                        cmd += ['-af', af]
                else:
                    # Video container output: copy video stream to avoid heavy re-encode
                    cmd += ['-c:v', 'copy']
                    # audio codec for container
                    cmd += self._audio_bitrate_args(out_ext_lower)
                    if af:
                        cmd += ['-af', af]

                cmd += [output_file]

                # Log command (sanitized)
                self.log_signal.emit('Running: ' + ' '.join([sh for sh in cmd]))

                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1)

                duration = None
                time_pattern = re.compile(r'time=(\d+):(\d+):(\d+\.\d+)')
                duration_pattern = re.compile(r'Duration:\s*(\d+):(\d+):(\d+\.\d+)')

                for line in process.stdout:
                    if self._stop_requested:
                        process.terminate()
                        self.finished.emit(False, 'Conversion stopped by user')
                        return

                    self.log_signal.emit(line.rstrip())

                    # Parse duration
                    if 'Duration' in line and not duration:
                        m = duration_pattern.search(line)
                        if m:
                            h, mm, ss = m.groups()
                            duration = int(h) * 3600 + int(mm) * 60 + float(ss)

                    # Parse current time
                    if 'time=' in line and duration:
                        m = time_pattern.search(line)
                        if m:
                            h, mm, ss = m.groups()
                            current = int(h) * 3600 + int(mm) * 60 + float(ss)
                            try:
                                prog = int((current / duration) * 100)
                                self.progress.emit(prog)
                            except Exception:
                                pass

                process.wait()

                if process.returncode != 0:
                    self.finished.emit(False, f"❌ Conversion failed for {input_file}")
                    return

                # Optional stems separation
                if self.separate_stems and SPLEETER_AVAILABLE:
                    try:
                        self.log_signal.emit('Separating stems with Spleeter...')
                        sep = Separator('spleeter:2stems')
                        sep.separate_to_file(output_file, self.output_folder)
                        self.log_signal.emit('Stems saved.')
                    except Exception as e:
                        self.log_signal.emit(f'Spleeter failed: {e}')

            self.finished.emit(True, '✅ All conversions finished successfully!')
        except Exception as e:
            self.finished.emit(False, str(e))
