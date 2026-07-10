// static/js/i18n.js — Multi-language support for Prophetis-branded Odysseus
// Detects language from ?lang= URL parameter and exposes translation helpers

(function () {
  'use strict';

  const TRANSLATIONS = {
    en: {
      role_ai: 'Prophetis',
      chat_title: 'Prophetis',
      compacting: 'Compacting context',
      research_timeout: 'Research clarification timed out. Toggle research again to start over.',
      new_chat: 'New Chat',
      search_placeholder: 'Search memories\u2026',
      btn_select: 'Select',
      btn_delete: 'Delete',
      btn_import: 'Import',
      btn_export: 'Export',
      btn_approve: 'Approve',
      btn_audit: 'Audit',
      btn_save: 'Save',
      btn_cancel: 'Cancel',
      btn_add: 'Add',
      all: 'all',
      selected: 'Selected',
      default_themes: 'Default Themes',
      your_themes: 'Your Themes',
      theme_saved: 'Theme saved',
      memory_settings: 'Settings',
      auto_extract_memories: 'Auto-extract memories',
      auto_extract_skills: 'Auto-extract skills',
      inject_skills: 'Inject Skills',
      auto_approve_skills: 'Auto-approve skills',
      max_skills: 'Max skills per request',
      min_confidence: 'Minimum confidence',
    },
    zh: {
      role_ai: '\u5148\u77e5',
      chat_title: 'Prophetis',
      compacting: '\u538b\u7f29\u4e0a\u4e0b\u6587',
      research_timeout: '\u7814\u7a76\u6e05\u695a\u65f6\u95f4\u8d85\u3002\u8bf7\u518d\u6b21\u5207\u6362\u7814\u7a76\u6a21\u5f0f\u91cd\u65b0\u5f00\u59cb\u3002',
      new_chat: '\u65b0\u5efa\u804a\u5929',
      search_placeholder: '\u641c\u7d22\u8bb0\u5fc6\u2026',
      btn_select: '\u9009\u62e9',
      btn_delete: '\u5220\u9664',
      btn_import: '\u5bfc\u5165',
      btn_export: '\u5bfc\u51fa',
      btn_approve: '\u6279\u51c6',
      btn_audit: '\u5ba1\u8ba1',
      btn_save: '\u4fdd\u5b58',
      btn_cancel: '\u53d6\u6d88',
      btn_add: '\u6dfb\u52a0',
      all: '\u5168\u90e8',
      selected: '\u5df2\u9009\u62e9',
      default_themes: '\u9ed8\u8ba4\u4e3b\u9898',
      your_themes: '\u6211\u7684\u4e3b\u9898',
      theme_saved: '\u4e3b\u9898\u5df2\u4fdd\u5b58',
      memory_settings: '\u8bbe\u7f6e',
      auto_extract_memories: '\u81ea\u52a8\u63d0\u53d6\u8bb0\u5fc6',
      auto_extract_skills: '\u81ea\u52a8\u63d0\u53d6\u6280\u80fd',
      inject_skills: '\u6ce8\u5165\u6280\u80fd',
      auto_approve_skills: '\u81ea\u52a8\u6279\u51c6\u6280\u80fd',
      max_skills: '\u6bcf\u6b21\u8bf7\u6c42\u6700\u5927\u6280\u80fd\u6570',
      min_confidence: '\u6700\u4f4e\u7f6e\u4fe1\u5ea6',
    },
    ja: {
      role_ai: '\u30d7\u30ed\u30d5\u30a7\u30c6\u30a3\u30b9',
      chat_title: 'Prophetis',
      compacting: '\u30b3\u30f3\u30c6\u30ad\u30b9\u30c8\u3092\u5727\u7e2e\u4e2d',
      research_timeout: '\u30ea\u30b5\u30fc\u30c1\u78ba\u8a8d\u304c\u30bf\u30a4\u30e0\u30a2\u30a6\u30c8\u3057\u307e\u3057\u305f\u3002\u30ea\u30b5\u30fc\u30c1\u3092\u5207\u308a\u66ff\u3048\u3066\u518d\u5ea6\u59cb\u3081\u3066\u304f\u3060\u3055\u3044\u3002',
      new_chat: '\u65b0\u898f\u30c1\u30e3\u30c3\u30c8',
      search_placeholder: '\u30e1\u30e2\u30ea\u30fc\u3092\u691c\u7d22\u2026',
      btn_select: '\u9078\u629e',
      btn_delete: '\u524a\u9664',
      btn_import: '\u30a4\u30f3\u30dd\u30fc\u30c8',
      btn_export: '\u30a8\u30af\u30b9\u30dd\u30fc\u30c8',
      btn_approve: '\u627f\u8a8d',
      btn_audit: '\u30aa\u30fc\u30c7\u30a3\u30c3\u30c8',
      btn_save: '\u4fdd\u5b58',
      btn_cancel: '\u30ad\u30e3\u30f3\u30bb\u30eb',
      btn_add: '\u8ffd\u52a0',
      all: '\u3059\u3079\u3066',
      selected: '\u9078\u629e\u4e2d',
      default_themes: '\u30c7\u30d5\u30a9\u30eb\u30c8\u30c6\u30fc\u30de',
      your_themes: '\u30de\u30a4\u30c6\u30fc\u30de',
      theme_saved: '\u30c6\u30fc\u30de\u3092\u4fdd\u5b58\u3057\u307e\u3057\u305f',
      memory_settings: '\u8a2d\u5b9a',
      auto_extract_memories: '\u8a18\u61b6\u3092\u81ea\u52d5\u63d0\u53d6',
      auto_extract_skills: '\u30b9\u30ad\u30eb\u3092\u81ea\u52d5\u63d0\u53d6',
      inject_skills: '\u30b9\u30ad\u30eb\u306e\u6ce8\u5165',
      auto_approve_skills: '\u30b9\u30ad\u30eb\u3092\u81ea\u52d5\u627f\u8a8d',
      max_skills: '\u30ea\u30af\u30a8\u30b9\u30c8\u6bce\u306e\u6700\u5927\u30b9\u30ad\u30eb\u6570',
      min_confidence: '\u6700\u4f4e\u7f6e\u4fe1\u5ea6',
    },
  };

  function detectLanguage() {
    try {
      var params = new URLSearchParams(window.location.search);
      var langParam = params.get('lang');
      if (langParam && TRANSLATIONS[langParam]) return langParam;
    } catch (_) {}
    var browserLang = (navigator.language || '').split('-')[0];
    if (TRANSLATIONS[browserLang]) return browserLang;
    return 'en';
  }

  var lang = detectLanguage();

  // Set lang attribute on HTML element
  document.documentElement.setAttribute('lang', lang);

  window.__appLang = lang;
  window.__t = function (key, fallback) {
    var map = TRANSLATIONS[lang];
    return (map && map[key]) || fallback || key;
  };
  // Also expose raw translations for advanced use
  window.__locale = lang;
  window.__translations = TRANSLATIONS;
})();
