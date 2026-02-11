document.addEventListener('DOMContentLoaded', function() {
    const ciServicesList = document.getElementById('ci-list'); // Fixed id to match popup.html
    const llmProviderSelectEl = document.getElementById('llm-provider-select');
    const llmModelEl = document.getElementById('llm-model');
    const openSettingsBtn = document.getElementById('open-settings');

    function normalizeLLMSettings(raw) {
        const s = raw || {};
        return {
            provider: s.provider || 'ollama',
            model: s.model || 'gemma3:12b',
            ollamaModel: s.ollamaModel || 'gemma3:12b',
            openaiModel: s.openaiModel || 'gpt-4o-mini',
            xaiModel: s.xaiModel || 'grok-2-latest',
            groqModel: s.groqModel || 'llama-3.3-70b-versatile',
            openaiApiKey: s.openaiApiKey || '',
            xaiApiKey: s.xaiApiKey || '',
            groqApiKey: s.groqApiKey || ''
        };
    }

    async function loadLLMSettings() {
        try {
            const stored = await chrome.storage.local.get(['llmSettings']);
            const settings = normalizeLLMSettings(stored.llmSettings);
            
            // Update dropdown options - disable providers without credentials
            const options = llmProviderSelectEl.querySelectorAll('option');
            options.forEach(option => {
                const provider = option.value;
                let hasCredentials = provider === 'ollama'; // Ollama always available
                
                if (provider === 'openai' && settings.openaiApiKey) hasCredentials = true;
                if (provider === 'xai' && settings.xaiApiKey) hasCredentials = true;
                if (provider === 'groq' && settings.groqApiKey) hasCredentials = true;
                
                option.disabled = !hasCredentials;
                if (!hasCredentials) {
                    option.textContent = option.textContent.split(' (')[0] + ' (not configured)';
                }
            });
            
            // Set current provider
            llmProviderSelectEl.value = settings.provider;
            
            // Show the model for the current provider
            const currentModel = settings.provider === 'ollama' ? settings.ollamaModel
                : settings.provider === 'xai' ? settings.xaiModel
                : settings.provider === 'groq' ? settings.groqModel
                : settings.openaiModel;
            llmModelEl.textContent = currentModel;
        } catch (e) {
            llmModelEl.textContent = '-';
        }
    }
    
    // Save provider selection when changed
    if (llmProviderSelectEl) {
        llmProviderSelectEl.addEventListener('change', async (e) => {
            const newProvider = e.target.value;
            const stored = await chrome.storage.local.get(['llmSettings']);
            const settings = normalizeLLMSettings(stored.llmSettings);
            settings.provider = newProvider;
            
            // Get the saved model for the selected provider
            const providerModel = newProvider === 'ollama' ? settings.ollamaModel
                : newProvider === 'xai' ? settings.xaiModel
                : newProvider === 'groq' ? settings.groqModel
                : settings.openaiModel;
            
            settings.model = providerModel; // Update legacy field
            
            await chrome.storage.local.set({ llmSettings: settings });
            
            // Update model display
            llmModelEl.textContent = providerModel;
        });
    }

    // Function to update the popup UI with detected CI services
    function updateUIServices(services) {
        ciServicesList.innerHTML = ''; // Clear previous results
        if (services.length === 0) {
            ciServicesList.innerHTML = '<li>No CI services detected.</li>';
        } else {
            services.forEach(service => {
                const listItem = document.createElement('li');
                // Handle both string and object formats
                listItem.textContent = typeof service === 'string' ? service : (service.text || service.name || 'Unknown CI');
                ciServicesList.appendChild(listItem);
            });
        }
    }

    // Function to fetch CI services from the content script
    function fetchCiServices() {
        chrome.tabs.query({ active: true, currentWindow: true }, function(tabs) {
            chrome.tabs.sendMessage(tabs[0].id, { action: 'getCiServices' }, function(response) {
                if (response && response.services) {
                    updateUIServices(response.services);
                } else {
                    updateUIServices([]);
                }
            });
        });
    }

    // Fetch CI services when the popup is opened
    fetchCiServices();

    // Load LLM settings in popup
    loadLLMSettings();

    // Open settings/options page
    if (openSettingsBtn) {
        openSettingsBtn.addEventListener('click', () => {
            if (chrome.runtime.openOptionsPage) {
                chrome.runtime.openOptionsPage();
            }
        });
    }
});