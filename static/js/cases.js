import documentModule from './document.js';

function getLanguageFromExtension(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    const map = {
        'md': 'markdown',
        'csv': 'csv',
        'html': 'html',
        'py': 'python',
        'js': 'javascript',
        'ts': 'typescript',
        'json': 'json',
        'txt': 'text',
        'xml': 'xml',
        'css': 'css'
    };
    return map[ext] || 'text';
}

export default {
    init: function() {
        this.fetchCases();
        this.initSectionToggle();
    },
    initSectionToggle: function() {
        const titleBtn = document.getElementById('cases-section-title');
        const toggleBtn = document.getElementById('cases-toggle-btn');
        const list = document.getElementById('cases-list');
        
        const toggleList = () => {
            const isHidden = list.style.display === 'none';
            list.style.display = isHidden ? 'flex' : 'none';
            if (toggleBtn) {
                const chevron = toggleBtn.querySelector('.section-chevron');
                if (chevron) {
                    chevron.style.transform = isHidden ? 'rotate(0deg)' : 'rotate(-90deg)';
                }
            }
        };

        if (titleBtn && list) {
            titleBtn.addEventListener('click', toggleList);
        }
        if (toggleBtn && list) {
            toggleBtn.addEventListener('click', toggleList);
        }
    },
    fetchCases: async function() {
        try {
            const res = await fetch('/api/cases/');
            if (!res.ok) return;
            const cases = await res.json();
            this.renderCases(cases);
        } catch (e) {
            console.error('Failed to fetch cases:', e);
        }
    },
    renderCases: function(cases) {
        const list = document.getElementById('cases-list');
        if (!list) return;
        list.innerHTML = '';
        cases.forEach(c => {
            // Folder item
            const folderDiv = document.createElement('div');
            folderDiv.className = 'list-item';
            folderDiv.style.cursor = 'pointer';
            folderDiv.innerHTML = `
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;opacity:0.5;">
                    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
                </svg>
                <span class="grow">${c.name}</span>
                <svg class="folder-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="transition: transform 0.2s; opacity: 0.5;">
                    <polyline points="9 18 15 12 9 6"></polyline>
                </svg>
            `;
            
            // Files container
            const filesContainer = document.createElement('div');
            filesContainer.style.display = 'none';
            filesContainer.style.flexDirection = 'column';
            filesContainer.style.paddingLeft = '18px';
            filesContainer.style.marginTop = '2px';
            filesContainer.style.marginBottom = '4px';

            c.files.forEach(f => {
                const fileDiv = document.createElement('div');
                fileDiv.className = 'list-item case-file-link';
                fileDiv.setAttribute('data-case', c.id);
                fileDiv.setAttribute('data-file', f);
                fileDiv.style.cursor = 'pointer';
                fileDiv.style.minHeight = '28px'; // Slightly smaller than normal list-item
                fileDiv.innerHTML = `
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;opacity:0.5;">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                        <polyline points="14 2 14 8 20 8"></polyline>
                    </svg>
                    <span class="grow" style="font-size: 0.9em; opacity: 0.8;">${f}</span>
                `;
                filesContainer.appendChild(fileDiv);
            });

            // Toggle logic
            folderDiv.addEventListener('click', () => {
                const isHidden = filesContainer.style.display === 'none';
                filesContainer.style.display = isHidden ? 'flex' : 'none';
                const chevron = folderDiv.querySelector('.folder-chevron');
                if (chevron) {
                    chevron.style.transform = isHidden ? 'rotate(90deg)' : 'rotate(0deg)';
                }
            });

            list.appendChild(folderDiv);
            list.appendChild(filesContainer);
        });

        // Add event listeners to files
        list.querySelectorAll('.case-file-link').forEach(el => {
            el.addEventListener('click', async (e) => {
                const target = e.currentTarget;
                const caseId = target.getAttribute('data-case');
                const file = target.getAttribute('data-file');
                try {
                    const res = await fetch(`/api/cases/${caseId}/${file}`);
                    const data = await res.json();
                    
                    // Inject into Odysseus Document system for proper rendering
                    const docObj = {
                        id: `case-${caseId}-${file}`,
                        title: `${caseId} / ${file}`,
                        current_content: data.content,
                        language: getLanguageFromExtension(file),
                        updated_at: new Date().toISOString()
                    };
                    documentModule.injectFreshDoc(docObj);
                } catch (err) {
                    console.error('Failed to load file', err);
                }
            });
        });
    }
};
