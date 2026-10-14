/**
 * VoiceCSV Analytics Agent - Speech-to-Text (STT) Module
 * Handles browser-native Web Speech API speech recognition.
 */

class SpeechToTextController {
  constructor(options = {}) {
    this.micBtn = document.getElementById(options.micBtnId || 'micBtn');
    this.micLabel = document.getElementById(options.micLabelId || 'micLabel');
    this.statusContainer = document.getElementById(options.statusContainerId || 'sttStatus');
    this.statusText = document.getElementById(options.statusTextId || 'sttStatusText');
    this.inputTarget = document.getElementById(options.inputTargetId || 'questionInput');
    
    this.recognition = null;
    this.isListening = false;
    this.isSupported = false;

    this.init();
  }

  init() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

    if (!SpeechRecognition) {
      this.isSupported = false;
      this.updateStatus('Speech not supported', 'disabled');
      if (this.micBtn) {
        this.micBtn.title = 'Speech recognition is not supported in this browser. Please type your query.';
        this.micBtn.classList.add('disabled');
      }
      return;
    }

    this.isSupported = true;
    try {
      this.recognition = new SpeechRecognition();
      this.recognition.continuous = false;
      this.recognition.interimResults = true;
      this.recognition.lang = 'en-US';

      this.recognition.onstart = () => this.handleStart();
      this.recognition.onresult = (event) => this.handleResult(event);
      this.recognition.onerror = (event) => this.handleError(event);
      this.recognition.onend = () => this.handleEnd();

      if (this.micBtn) {
        this.micBtn.addEventListener('click', () => this.toggleListening());
      }
    } catch (err) {
      console.warn('SpeechRecognition initialization error:', err);
      this.isSupported = false;
      this.updateStatus('Speech unavailable', 'disabled');
    }
  }

  toggleListening() {
    if (!this.isSupported) {
      alert('Speech recognition is not supported by your browser. Please type your question directly.');
      return;
    }

    if (this.isListening) {
      this.stop();
    } else {
      this.start();
    }
  }

  start() {
    if (!this.recognition || this.isListening) return;
    try {
      this.recognition.start();
    } catch (err) {
      console.warn('Failed to start speech recognition:', err);
      this.handleEnd();
    }
  }

  stop() {
    if (!this.recognition || !this.isListening) return;
    try {
      this.recognition.stop();
    } catch (err) {
      console.warn('Failed to stop speech recognition:', err);
      this.handleEnd();
    }
  }

  handleStart() {
    this.isListening = true;
    if (this.micBtn) {
      this.micBtn.classList.add('active');
    }
    if (this.micLabel) {
      this.micLabel.textContent = 'Listening...';
    }
    this.updateStatus('Listening...', 'recording');
  }

  handleResult(event) {
    let transcript = '';
    for (let i = event.resultIndex; i < event.results.length; ++i) {
      transcript += event.results[i][0].transcript;
    }

    if (this.inputTarget && transcript.trim()) {
      this.inputTarget.value = transcript;
      // Trigger input event in case listeners exist
      this.inputTarget.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }

  handleError(event) {
    console.warn('SpeechRecognition error:', event.error);
    let msg = 'Ready';
    if (event.error === 'not-allowed') {
      msg = 'Mic access denied';
    } else if (event.error === 'no-speech') {
      msg = 'No speech detected';
    } else if (event.error === 'network') {
      msg = 'Speech network error';
    } else {
      msg = `Speech error (${event.error})`;
    }
    this.updateStatus(msg, 'error');
  }

  handleEnd() {
    this.isListening = false;
    if (this.micBtn) {
      this.micBtn.classList.remove('active');
    }
    if (this.micLabel) {
      this.micLabel.textContent = 'Speak';
    }
    setTimeout(() => {
      this.updateStatus('Ready', 'idle');
    }, 2000);
  }

  updateStatus(text, state) {
    if (this.statusText) {
      this.statusText.textContent = text;
    }
    if (this.statusContainer) {
      this.statusContainer.className = 'speech-status-indicator';
      if (state === 'recording') {
        this.statusContainer.classList.add('recording');
      }
    }
  }
}

// Instantiate and expose globally
window.sttController = new SpeechToTextController();
