import { pipeline, env } from '@xenova/transformers';

// Explicitly enable browser caching for models
env.allowLocalModels = false;
env.useBrowserCache = true; // Use IndexedDB for storage
// Use WASM proxy if available for better performance
env.backends.onnx.wasm.proxy = true;

class PipelineFactory {
    static task = 'automatic-speech-recognition';
    static model = 'Xenova/whisper-tiny.en';
    static instance = null;

    static async getInstance(progress_callback = null) {
        if (this.instance === null) {
            this.instance = await pipeline(this.task, this.model, {
                progress_callback,
                device: 'webgpu' // Will fallback to wasm if webgpu is not available
            }).catch(async (e) => {
                console.warn("WebGPU not available, falling back to WASM", e);
                // Fallback explicitly to WASM if webgpu fails entirely
                return await pipeline(this.task, this.model, {
                    progress_callback
                });
            });
        }
        return this.instance;
    }
}

// Listen for messages from the main thread
self.addEventListener('message', async (event) => {
    const message = event.data;

    // Handle initialization request
    if (message.type === 'load') {
        try {
            await PipelineFactory.getInstance((data) => {
                self.postMessage({
                    type: 'progress',
                    ...data
                });
            });
            self.postMessage({ type: 'ready' });
        } catch (error) {
            self.postMessage({ type: 'error', error: error.message });
        }
    }

    // Handle audio transcription
    if (message.type === 'transcribe') {
        try {
            const transcriber = await PipelineFactory.getInstance();
            
            // Output format depends on the model, whisper returns an object with text
            const output = await transcriber(message.audio, {
                chunk_length_s: 30,
                stride_length_s: 5,
                language: 'english',
                task: 'transcribe',
            });

            self.postMessage({
                type: 'result',
                text: output.text,
                isFinal: message.isFinal || false
            });
        } catch (error) {
            console.error("Transcription error", error);
            self.postMessage({ type: 'error', error: error.message });
        }
    }
});
