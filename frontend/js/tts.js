/**
 * VoiceCSV Analytics Agent - Text-to-Speech (TTS) Module
 * Handles browser-native SpeechSynthesis audio playback for executive summaries.
 */

class TextToSpeechController {
  constructor(options = {}) {
    this.playBtn = document.getElementById(options.playBtnId || 'readSummaryBtn');
    this.stopBtn = document.getElementById(options.stopBtnId || 'stopSummaryBtn');
    this.playBtnText = document.getElementById(options.playBtnTextId || 'ttsBtnText');
    this.textTarget = document.getElementById(options.textTargetId || 'executiveSummaryText');

    this.synth = window.speechSynthesis || null;
    this.currentUtterance = null;
    this.isPlaying = false;
    this.voices = [];

    this.init();
  }

  init() {
    if (!this.synth) {
      if (this.playBtn) {
        this.playBtn.title = 'Speech synthesis is not supported in this browser.';
        this.playBtn.classList.add('disabled');
      }
      return;
    }

    // Load voices
    this.loadVoices();
    if (speechSynthesis.onvoiceschanged !== undefined) {
      speechSynthesis.onvoiceschanged = () => this.loadVoices();
    }

    if (this.playBtn) {
      this.playBtn.addEventListener('click', () => this.toggleSpeech());
    }

    if (this.stopBtn) {
      this.stopBtn.addEventListener('click', () => this.stop());
    }
  }

  loadVoices() {
    if (!this.synth) return;
    try {
      this.voices = this.synth.getVoices();
    } catch (e) {
      console.warn('Could not retrieve speech voices:', e);
    }
  }

  getBestVoice() {
    if (!this.voices || this.voices.length === 0) return null;
    
    // Prefer English voices with natural qualities
    const preferredNames = ['Google US English', 'Microsoft Jenny', 'Samantha', 'Alex', 'Natural'];
    for (const name of preferredNames) {
      const match = this.voices.find(v => v.name.includes(name) && v.lang.startsWith('en'));
      if (match) return match;
    }

    // Default to any English voice
    const anyEn = this.voices.find(v => v.lang.startsWith('en'));
    return anyEn || this.voices[0] || null;
  }

  toggleSpeech() {
    if (this.isPlaying) {
      this.stop();
    } else {
      this.play();
    }
  }

  play() {
    if (!this.synth) return;

    const textToSpeak = this.textTarget ? this.textTarget.textContent.trim() : '';
    if (!textToSpeak) return;

    // Stop any existing utterance
    this.stop();

    try {
      this.currentUtterance = new SpeechSynthesisUtterance(textToSpeak);
      this.currentUtterance.rate = 1.0;
      this.currentUtterance.pitch = 1.0;

      const voice = this.getBestVoice();
      if (voice) {
        this.currentUtterance.voice = voice;
      }

      this.currentUtterance.onstart = () => {
        this.isPlaying = true;
        this.updateUI(true);
      };

      this.currentUtterance.onend = () => {
        this.isPlaying = false;
        this.updateUI(false);
      };

      this.currentUtterance.onerror = (e) => {
        console.warn('Speech synthesis error:', e);
        this.isPlaying = false;
        this.updateUI(false);
      };

      this.synth.speak(this.currentUtterance);
    } catch (err) {
      console.warn('SpeechSynthesis error:', err);
      this.isPlaying = false;
      this.updateUI(false);
    }
  }

  stop() {
    if (!this.synth) return;
    try {
      this.synth.cancel();
    } catch (e) {
      console.warn('Error cancelling speech synthesis:', e);
    }
    this.isPlaying = false;
    this.updateUI(false);
  }

  updateUI(speaking) {
    if (this.playBtn) {
      if (speaking) {
        this.playBtn.classList.add('active');
        if (this.playBtnText) this.playBtnText.textContent = 'Speaking...';
      } else {
        this.playBtn.classList.remove('active');
        if (this.playBtnText) this.playBtnText.textContent = 'Listen';
      }
    }

    if (this.stopBtn) {
      if (speaking) {
        this.stopBtn.classList.remove('hidden');
      } else {
        this.stopBtn.classList.add('hidden');
      }
    }
  }
}

// Instantiate and expose globally
window.ttsController = new TextToSpeechController();
