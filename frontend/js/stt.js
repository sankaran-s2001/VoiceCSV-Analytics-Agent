/**
 * VoiceCSV Analytics Agent - Speech-to-Text (STT) Module
 * Supports both browser-native Web Speech API and MediaRecorder + Gemini server fallback.
 */

class SpeechToTextController {
  constructor(options = {}) {
    this.micBtn = document.getElementById(options.micBtnId || 'micBtn');
    this.micLabel = document.getElementById(options.micLabelId || 'micLabel');
    this.statusContainer = document.getElementById(options.statusContainerId || 'sttStatus');
    this.statusText = document.getElementById(options.statusTextId || 'sttStatusText');
    this.inputTarget = document.getElementById(options.inputTargetId || 'questionInput');

    this.recognition = null;
    this.mediaRecorder = null;
    this.audioChunks = [];
    this.mediaStream = null;
    this.recordTimeout = null;

    this.isListening = false;
    this.engine = 'none'; // 'native' | 'recorder' | 'none'

    this.init();
  }

  init() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

    if (SpeechRecognition) {
      this.engine = 'native';
      try {
        this.recognition = new SpeechRecognition();
        this.recognition.continuous = false;
        this.recognition.interimResults = true;
        this.recognition.lang = 'en-US';

        this.recognition.onstart = () => this.handleNativeStart();
        this.recognition.onresult = (e) => this.handleNativeResult(e);
        this.recognition.onerror = (e) => this.handleNativeError(e);
        this.recognition.onend = () => this.handleNativeEnd();
      } catch (err) {
        console.warn('Native SpeechRecognition init failed, falling back to MediaRecorder:', err);
        this.engine = 'recorder';
      }
    } else if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder) {
      this.engine = 'recorder';
    } else {
      this.engine = 'none';
    }

    if (this.engine === 'none') {
      // Hide status indicator cleanly to avoid broken-looking watermark
      if (this.statusContainer) {
        this.statusContainer.classList.add('hidden');
      }
      if (this.micBtn) {
        this.micBtn.title = 'Microphone access is not available in this browser environment.';
      }
      return;
    }

    // Set initial ready state
    this.updateStatus('Ready', 'idle');
    if (this.statusContainer) {
      this.statusContainer.classList.remove('hidden');
    }

    if (this.micBtn) {
      this.micBtn.classList.remove('disabled');
      this.micBtn.title = this.engine === 'native'
        ? 'Speak question using browser speech recognition'
        : 'Record question using microphone (transcribed by Gemini)';
      this.micBtn.addEventListener('click', () => this.toggleListening());
    }
  }

  toggleListening() {
    if (this.isListening) {
      this.stop();
    } else {
      this.start();
    }
  }

  start() {
    if (this.isListening) return;

    if (this.engine === 'native' && this.recognition) {
      try {
        this.recognition.start();
      } catch (err) {
        console.warn('Native recognition start failed, trying MediaRecorder fallback:', err);
        this.startMediaRecorder();
      }
    } else if (this.engine === 'recorder' || (navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) {
      this.startMediaRecorder();
    } else {
      alert('Microphone input is not available in this browser context.');
    }
  }

  stop() {
    if (!this.isListening) return;

    if (this.recordTimeout) {
      clearTimeout(this.recordTimeout);
      this.recordTimeout = null;
    }

    if (this.recognition && this.engine === 'native') {
      try {
        this.recognition.stop();
      } catch (e) {
        // Suppress
      }
    }

    if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      try {
        this.mediaRecorder.stop();
      } catch (e) {
        // Suppress
      }
    }
  }

  // Native Web Speech API Handlers
  handleNativeStart() {
    this.isListening = true;
    if (this.micBtn) this.micBtn.classList.add('active');
    if (this.micLabel) this.micLabel.textContent = 'Listening...';
    this.updateStatus('Listening...', 'recording');
  }

  handleNativeResult(event) {
    let transcript = '';
    for (let i = event.resultIndex; i < event.results.length; ++i) {
      transcript += event.results[i][0].transcript;
    }
    if (this.inputTarget && transcript.trim()) {
      this.inputTarget.value = transcript;
      this.inputTarget.dataset.source = 'voice';
      this.inputTarget.dispatchEvent(new CustomEvent('speech-transcribed', { detail: { text: transcript }, bubbles: true }));
      this.inputTarget.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }

  handleNativeError(event) {
    console.warn('SpeechRecognition error:', event.error);
    if (event.error === 'not-allowed') {
      this.updateStatus('Mic access denied', 'error');
    } else if (event.error === 'no-speech') {
      this.updateStatus('No speech detected', 'error');
    } else if (event.error === 'network') {
      console.warn('Native speech network error; switching to MediaRecorder fallback.');
      this.engine = 'recorder';
      this.startMediaRecorder();
      return;
    } else {
      this.updateStatus('Speech error', 'error');
    }
    this.handleNativeEnd();
  }

  handleNativeEnd() {
    this.isListening = false;
    if (this.micBtn) this.micBtn.classList.remove('active');
    if (this.micLabel) this.micLabel.textContent = 'Speak';
    setTimeout(() => {
      this.updateStatus('Ready', 'idle');
    }, 1800);
  }

  // MediaRecorder + Gemini Server Transcription Fallback
  async startMediaRecorder() {
    try {
      this.audioChunks = [];
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.mediaStream = stream;

      let mimeType = 'audio/webm';
      if (typeof MediaRecorder.isTypeSupported === 'function') {
        if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
          mimeType = 'audio/webm;codecs=opus';
        } else if (MediaRecorder.isTypeSupported('audio/webm')) {
          mimeType = 'audio/webm';
        } else if (MediaRecorder.isTypeSupported('audio/ogg;codecs=opus')) {
          mimeType = 'audio/ogg;codecs=opus';
        } else if (MediaRecorder.isTypeSupported('audio/mp4')) {
          mimeType = 'audio/mp4';
        }
      }

      this.mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      this.isListening = true;

      this.mediaRecorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) {
          this.audioChunks.push(e.data);
        }
      };

      this.mediaRecorder.onstop = async () => {
        this.cleanupStream();
        await this.handleRecorderStop(mimeType);
      };

      this.mediaRecorder.start(250);

      if (this.micBtn) this.micBtn.classList.add('active');
      if (this.micLabel) this.micLabel.textContent = 'Stop';
      this.updateStatus('Recording... (click Stop)', 'recording');

      // Auto-stop after 15 seconds max
      this.recordTimeout = setTimeout(() => {
        if (this.isListening) {
          this.stop();
        }
      }, 15000);

    } catch (err) {
      console.error('Microphone access failed:', err);
      this.isListening = false;
      this.cleanupStream();
      this.updateStatus('Mic permission needed', 'error');
      if (this.micBtn) this.micBtn.classList.remove('active');
      if (this.micLabel) this.micLabel.textContent = 'Speak';
      setTimeout(() => this.updateStatus('Ready', 'idle'), 3000);
    }
  }

  cleanupStream() {
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach(track => track.stop());
      this.mediaStream = null;
    }
  }

  async handleRecorderStop(mimeType) {
    this.isListening = false;
    if (this.micBtn) this.micBtn.classList.remove('active');
    if (this.micLabel) this.micLabel.textContent = 'Speak';

    if (!this.audioChunks || this.audioChunks.length === 0) {
      this.updateStatus('Ready', 'idle');
      return;
    }

    const audioBlob = new Blob(this.audioChunks, { type: mimeType || 'audio/webm' });
    this.updateStatus('Transcribing...', 'recording');

    try {
      const formData = new FormData();
      formData.append('file', audioBlob, 'question_audio.webm');

      const res = await fetch('/api/transcribe', {
        method: 'POST',
        body: formData
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Server returned ${res.status}`);
      }

      const data = await res.json();
      const text = (data.text || '').trim();

      if (text && this.inputTarget) {
        this.inputTarget.value = text;
        this.inputTarget.dataset.source = 'voice';
        this.inputTarget.dispatchEvent(new CustomEvent('speech-transcribed', { detail: { text }, bubbles: true }));
        this.inputTarget.dispatchEvent(new Event('input', { bubbles: true }));
        this.updateStatus('Transcribed!', 'idle');
      } else {
        this.updateStatus('No speech recognized', 'idle');
      }
    } catch (err) {
      console.warn('Transcription request failed:', err);
      this.updateStatus('Transcription failed', 'error');
    } finally {
      setTimeout(() => {
        this.updateStatus('Ready', 'idle');
      }, 2500);
    }
  }

  updateStatus(text, state) {
    if (this.statusText) {
      this.statusText.textContent = text;
    }
    if (this.statusContainer) {
      this.statusContainer.className = 'speech-status-indicator';
      if (state === 'recording') {
        this.statusContainer.classList.add('recording');
      } else if (state === 'error') {
        this.statusContainer.classList.add('error');
      } else if (state === 'idle') {
        this.statusContainer.classList.add('ready');
      }
    }
  }
}

// Instantiate and expose globally when DOM is loaded
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    window.sttController = new SpeechToTextController();
  });
} else {
  window.sttController = new SpeechToTextController();
}
