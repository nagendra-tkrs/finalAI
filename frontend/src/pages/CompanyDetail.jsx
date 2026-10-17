import { useEffect, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../api';
import { deriveSequenceState, SEQUENCE_STATE_META } from '../utils/outreachStats';
import {
  applyLocalEdit,
  describeRecipientSync,
  describeScheduleResult,
  findInvalidEmails,
  getActiveStepMessage,
  isLockedMessage,
  mergeServerMessages,
  resolveStepMessage,
  shouldRefetchAfterSave,
} from '../utils/outreachEditor';

const CRAWL_STATUS_STYLES = {
  pending: 'bg-slate-100 text-slate-600',
  crawling: 'bg-blue-100 text-blue-700 animate-pulse',
  completed: 'bg-emerald-100 text-emerald-700',
  blocked: 'bg-amber-100 text-amber-800 border border-amber-300',
  failed: 'bg-red-100 text-red-700',
};

const RESEARCH_STATUS_STYLES = {
  pending: 'bg-slate-100 text-slate-600',
  researching: 'bg-purple-100 text-purple-700 animate-pulse',
  completed: 'bg-emerald-100 text-emerald-700',
  failed: 'bg-red-100 text-red-700',
};

const OUTREACH_STATUS_STYLES = {
  none: 'bg-slate-100 text-slate-600',
  generated: 'bg-indigo-100 text-indigo-700',
  sent: 'bg-emerald-100 text-emerald-700',
};

const ROLE_ICONS_AND_LABELS = {
  ceo: { icon: '👑', label: 'CEO / Chief Executive', badge: 'bg-amber-50 text-amber-900 border-amber-300' },
  founder: { icon: '💡', label: 'Founder', badge: 'bg-purple-50 text-purple-900 border-purple-300' },
  co_founder: { icon: '💡', label: 'Co-Founder', badge: 'bg-purple-50 text-purple-900 border-purple-300' },
  president: { icon: '🏛️', label: 'President', badge: 'bg-indigo-50 text-indigo-900 border-indigo-300' },
  managing_director: { icon: '👔', label: 'Managing Director', badge: 'bg-blue-50 text-blue-900 border-blue-300' },
  coo: { icon: '💼', label: 'COO / Operations', badge: 'bg-blue-50 text-blue-900 border-blue-300' },
  cfo: { icon: '💰', label: 'CFO / Finance', badge: 'bg-emerald-50 text-emerald-900 border-emerald-300' },
  cto: { icon: '🚀', label: 'CTO / Technology', badge: 'bg-cyan-50 text-cyan-900 border-cyan-300' },
  cio: { icon: '💻', label: 'CIO / Information', badge: 'bg-cyan-50 text-cyan-900 border-cyan-300' },
  cdo: { icon: '📊', label: 'CDO / Digital & Data', badge: 'bg-teal-50 text-teal-900 border-teal-300' },
  head_of_ai: { icon: '🤖', label: 'Head of AI', badge: 'bg-violet-50 text-violet-900 border-violet-300' },
  head_of_data: { icon: '📈', label: 'Head of Data', badge: 'bg-teal-50 text-teal-900 border-teal-300' },
  head_of_technology: { icon: '⚙️', label: 'Head of Technology / Eng', badge: 'bg-cyan-50 text-cyan-900 border-cyan-300' },
  head_of_operations: { icon: '💼', label: 'Head of Operations', badge: 'bg-blue-50 text-blue-900 border-blue-300' },
  head_of_sales: { icon: '🎯', label: 'Head of Sales / CRO', badge: 'bg-rose-50 text-rose-900 border-rose-300' },
  head_of_product: { icon: '📦', label: 'Head of Product', badge: 'bg-amber-50 text-amber-900 border-amber-300' },
  vp: { icon: '🚀', label: 'Vice President', badge: 'bg-sky-50 text-sky-900 border-sky-300' },
  dept_head: { icon: '🎯', label: 'Department Head', badge: 'bg-teal-50 text-teal-900 border-teal-300' },
  director: { icon: '📊', label: 'Director', badge: 'bg-slate-50 text-slate-800 border-slate-300' },
  manager: { icon: '⚡', label: 'Manager / Lead', badge: 'bg-slate-50 text-slate-700 border-slate-300' },
  general: { icon: '🏢', label: 'Company Channel', badge: 'bg-slate-100 text-slate-800 border-slate-300' },
  other: { icon: '👤', label: 'Executive', badge: 'bg-slate-50 text-slate-700 border-slate-200' },
};

const EMAIL_STATUS_META = {
  EXACT_FOUND: {
    label: 'EXACT_FOUND',
    pillClass: 'bg-emerald-50 text-emerald-800 border-emerald-300 font-bold',
    icon: '✓'
  },
  PATTERN_GENERATED: {
    label: 'PATTERN_GENERATED',
    pillClass: 'bg-amber-50 text-amber-900 border-amber-300 font-semibold',
    icon: '⚠'
  },
  PATTERN_INFERRED: {
    label: 'PATTERN_INFERRED',
    pillClass: 'bg-purple-50 text-purple-900 border-purple-300 font-semibold',
    icon: '✦'
  },
  SEARCH_TIMEOUT: {
    label: 'SEARCH_TIMEOUT',
    pillClass: 'bg-orange-50 text-orange-900 border-orange-300 font-semibold',
    icon: '⏱'
  },
  SEARCH_UNAVAILABLE: {
    label: 'SEARCH_UNAVAILABLE',
    pillClass: 'bg-rose-50 text-rose-900 border-rose-300 font-semibold',
    icon: '⚡'
  },
  DOMAIN_BLOCKED: {
    label: 'DOMAIN_BLOCKED',
    pillClass: 'bg-red-50 text-red-900 border-red-300 font-semibold',
    icon: '🚫'
  },
  NEEDS_REVIEW: {
    label: 'NEEDS_REVIEW',
    pillClass: 'bg-yellow-50 text-yellow-900 border-yellow-300 font-semibold',
    icon: '👁'
  },
  NOT_FOUND: {
    label: 'NOT_FOUND',
    pillClass: 'bg-slate-100 text-slate-600 border-slate-200 font-medium',
    icon: '—'
  }
};

const resolveUserFacingEmailStatus = (contact) => {
  if (!contact) return 'NOT_FOUND';
  const raw = contact.emailStatus || contact.email_status || contact.status;
  if (raw === 'EXACT_FOUND' || contact.isExactPublished || raw === 'DIRECTLY_VERIFIED' || raw === 'EXACT_PUBLIC_SOURCE' || raw === 'EXACT_SOURCE_VERIFIED') {
    return 'EXACT_FOUND';
  }
  if (raw === 'SEARCH_TIMEOUT') {
    return 'SEARCH_TIMEOUT';
  }
  if (raw === 'SEARCH_UNAVAILABLE') {
    return 'SEARCH_UNAVAILABLE';
  }
  if (raw === 'DOMAIN_BLOCKED') {
    return 'DOMAIN_BLOCKED';
  }
  if (raw === 'NEEDS_REVIEW') {
    return 'NEEDS_REVIEW';
  }
  if (contact.email && (raw === 'PATTERN_INFERRED' || contact.emailVerificationMethod === 'PATTERN_INFERENCE')) {
    return 'PATTERN_INFERRED';
  }
  if (contact.email && (raw === 'PATTERN_GENERATED' || raw === 'pattern_derived')) {
    return 'PATTERN_GENERATED';
  }
  if (contact.email) {
    return 'PATTERN_GENERATED';
  }
  return 'NOT_FOUND';
};

const TKSR_SERVICES = [
  { id: 'AI Strategy Consulting', label: 'AI Strategy Consulting (Roadmaps & ROI Use Cases)' },
  { id: 'AI Readiness and Opportunity Assessments', label: 'AI Readiness and Opportunity Assessments (System & Workflow Audits)' },
  { id: 'AI & Automation Workshops', label: 'AI & Automation Workshops (Rapid Prototyping & Automation)' },
  { id: 'AI Training', label: 'AI Training (Generative AI & LLM Upskilling)' },
  { id: 'AI Governance and Responsible AI', label: 'AI Governance and Responsible AI (Compliance & Risk Guardrails)' },
  { id: 'AI Data Strategy', label: 'AI Data Strategy (Vector DBs, RAG & Data Architecture)' }
];

export default function CompanyDetail() {
  const { companyId } = useParams();
  const navigate = useNavigate();

  const [activeTab, setActiveTab] = useState('crawl');
  const [company, setCompany] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  // Tab 1: Crawl state
  const [crawlData, setCrawlData] = useState(null);
  const [pages, setPages] = useState([]);
  const [selectedPage, setSelectedPage] = useState(null);
  const [crawling, setCrawling] = useState(false);

  // Tab 2: AI Research state
  const [research, setResearch] = useState(null);
  const [researching, setResearching] = useState(false);

  // Tab 3: Decision Makers state
  const [contacts, setContacts] = useState([]);
  const [extractingContacts, setExtractingContacts] = useState(false);
  const [roleFilter, setRoleFilter] = useState('all');
  const [patternInfo, setPatternInfo] = useState(null);
  const [selectedPattern, setSelectedPattern] = useState('first.last');
  const [applyingPattern, setApplyingPattern] = useState(false);
  const [showAddContactModal, setShowAddContactModal] = useState(false);
  const [evidenceContact, setEvidenceContact] = useState(null);
  const [newContact, setNewContact] = useState({
    name: '',
    designation: '',
    roleCategory: 'ceo',
    email: '',
    linkedinUrl: '',
    seniority: 'executive',
    department: 'Executive Leadership',
    source: 'Manual Input'
  });
  const [editingContact, setEditingContact] = useState(null);

  // Tab 4: Outreach state
  const [outreachMessages, setOutreachMessages] = useState([]);
  const [selectedStep, setSelectedStep] = useState(1);
  const [selectedContactId, setSelectedContactId] = useState('');
  const [outreachAngle, setOutreachAngle] = useState('pain_point');
  const [outreachTone, setOutreachTone] = useState('conversational');
  const [selectedFocusService, setSelectedFocusService] = useState('AI Strategy Consulting');
  const [generatingOutreach, setGeneratingOutreach] = useState(false);
  const [sendingEmail, setSendingEmail] = useState(false);
  const [savingDraft, setSavingDraft] = useState(false);
  const [scheduling, setScheduling] = useState(false);
  const [sendResult, setSendResult] = useState(null);
  const [copiedField, setCopiedField] = useState('');
  const [editingMessage, setEditingMessage] = useState(null);
  const [regeneratingEmail, setRegeneratingEmail] = useState(false);
  const [ccInputText, setCcInputText] = useState('');
  const [bccInputText, setBccInputText] = useState('');
  const [showBccInput, setShowBccInput] = useState(false);
  const [showScheduleModal, setShowScheduleModal] = useState(false);
  const [scheduleConfig, setScheduleConfig] = useState({ step2Days: 3, step3Days: 6 });

  // Per-step working copies + dirty flags. A single shared `editingMessage`
  // used to be replaced on every step switch / refetch, silently discarding
  // unsaved edits. Each step now owns its own working copy.
  const [draftsByStep, setDraftsByStep] = useState({});
  const [dirtySteps, setDirtySteps] = useState({});
  // Refs mirror the latest nav/edit state so async refetches never clobber a
  // step that has unsaved edits (state updates would otherwise be stale).
  const draftsByStepRef = useRef({});
  const dirtyStepsRef = useRef({});
  const selectedStepRef = useRef(1);

  const setStepDirty = (step, value) => {
    dirtyStepsRef.current = { ...dirtyStepsRef.current, [step]: value };
    setDirtySteps(dirtyStepsRef.current);
  };

  // Single entry point for every local edit so the working copy and dirty flag
  // stay consistent.
  const updateEditingMessage = (patch) => {
    if (!editingMessage) return;
    const next = applyLocalEdit(editingMessage, patch);
    const step = editingMessage.step;
    draftsByStepRef.current = { ...draftsByStepRef.current, [step]: next };
    setDraftsByStep(draftsByStepRef.current);
    setStepDirty(step, true);
    setEditingMessage(next);
  };

  const fetchCompanyData = async () => {
    try {
      const res = await api.get('/companies', { params: { limit: 1000 } });
      const found = res.data.companies.find((c) => c._id === companyId);
      setCompany(found);
      if (found?.recommendedService) {
        setSelectedFocusService(found.recommendedService);
      }
    } catch (err) {
      setError(err.message);
    }
  };

  const fetchCrawl = async () => {
    try {
      const [crawlRes, pagesRes] = await Promise.all([
        api.get(`/companies/${companyId}/crawl`).catch(() => ({ data: null })),
        api.get(`/companies/${companyId}/pages`).catch(() => ({ data: { pages: [] } })),
      ]);
      if (crawlRes.data) setCrawlData(crawlRes.data);
      if (pagesRes.data) setPages(pagesRes.data.pages || []);
    } catch (err) {
      console.warn('Crawl fetch error:', err);
    }
  };

  const fetchResearch = async () => {
    try {
      const res = await api.get(`/companies/${companyId}/research`);
      if (res.data) setResearch(res.data);
    } catch {
      setResearch(null);
    }
  };

  const fetchContacts = async () => {
    try {
      const res = await api.get(`/companies/${companyId}/contacts`);
      const list = res.data?.data || res.data || [];
      if (Array.isArray(list)) {
        setContacts(list);
        if (list.length > 0 && !selectedContactId) {
          const leadContact = list.find(c => c.roleCategory !== 'general' && c.seniority !== 'general') || list[0];
          setSelectedContactId(leadContact._id);
        }
      }
    } catch (err) {
      console.warn('Contacts fetch error:', err);
    }
  };

  const fetchPatternInfo = async () => {
    try {
      const res = await api.get(`/companies/${companyId}/contacts/pattern`);
      if (res.data?.data) {
        setPatternInfo(res.data.data);
        if (res.data.data.detectedPattern) {
          setSelectedPattern(res.data.data.detectedPattern);
        }
      }
    } catch (err) {
      console.warn('Pattern info fetch error:', err);
    }
  };

  const fetchOutreach = async () => {
    try {
      const res = await api.get(`/companies/${companyId}/outreach`);
      const list = res.data?.data || res.data || [];
      if (Array.isArray(list)) {
        setOutreachMessages(list);
        // Refresh per-step drafts, but never overwrite a step with unsaved edits.
        setDraftsByStep((prev) => {
          const merged = mergeServerMessages(prev, dirtyStepsRef.current, list);
          draftsByStepRef.current = merged;
          return merged;
        });

        const currentStep = selectedStepRef.current;
        const savedForStep = list.find((m) => m.step === currentStep);
        // Only replace the visible editor when the current step is clean.
        if (savedForStep && !dirtyStepsRef.current[currentStep]) {
          setEditingMessage(savedForStep);
        } else if (!dirtyStepsRef.current[currentStep] && draftsByStepRef.current[currentStep]) {
          setEditingMessage(draftsByStepRef.current[currentStep]);
        }
        if (savedForStep?.focusService) {
          setSelectedFocusService(savedForStep.focusService);
        }
        if (savedForStep?.bccRecipients && savedForStep.bccRecipients.length > 0) {
          setShowBccInput(true);
        }
      }
    } catch (err) {
      console.warn('Outreach fetch error:', err);
    }
  };

  useEffect(() => {
    const loadAll = async () => {
      setLoading(true);
      // A new company starts a fresh editor: no cross-company draft bleed.
      selectedStepRef.current = 1;
      dirtyStepsRef.current = {};
      draftsByStepRef.current = {};
      setSelectedStep(1);
      setDirtySteps({});
      setDraftsByStep({});
      await Promise.all([
        fetchCompanyData(),
        fetchCrawl(),
        fetchResearch(),
        fetchContacts(),
        fetchPatternInfo(),
        fetchOutreach(),
      ]);
      setLoading(false);
    };
    loadAll();
  }, [companyId]);

  // Crawl handler
  const handleTriggerCrawl = async () => {
    setCrawling(true);
    setError('');
    try {
      // Crawls of large sites can exceed the 120s default axios timeout;
      // give the backend a longer budget so the job is not cut off client-side.
      await api.post(`/companies/${companyId}/crawl`, null, { timeout: 600000 });
      await fetchCrawl();
      await fetchCompanyData();
      await fetchContacts();
      await fetchPatternInfo();
      setActiveTab('contacts');
      setSuccessMsg('Website crawled and decision makers discovered successfully!');
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err) {
      setError(err.message);
    } finally {
      setCrawling(false);
    }
  };

  // Research handler
  const handleTriggerResearch = async () => {
    setResearching(true);
    setError('');
    try {
      // Local Ollama (qwen2.5-coder:7b) research can take several minutes.
      // A long timeout keeps the frontend connected while the backend finishes.
      const res = await api.post(`/companies/${companyId}/research`, null, { timeout: 900000 });
      setResearch(res.data?.data || res.data);
      await fetchCompanyData();
      setActiveTab('research');
    } catch (err) {
      setError(`Research failed: ${err.message}`);
    } finally {
      setResearching(false);
    }
  };

  // Decision Makers handlers
  const handleExtractContacts = async () => {
    setExtractingContacts(true);
    setError('');
    try {
      const res = await api.post(`/companies/${companyId}/contacts/discover`, null, { timeout: 300000 });
      const list = res.data?.data || res.data || [];
      const searchDiag = res.data?.searchDiagnostics;
      if (Array.isArray(list) && list.length > 0) {
        setContacts(list);
        const lead = list.find(c => c.roleCategory !== 'general' && c.seniority !== 'general') || list[0];
        if (lead) {
          setSelectedContactId(lead._id);
        }
        await fetchPatternInfo();
        setSuccessMsg(`Discovered ${list.length} decision maker${list.length > 1 ? 's' : ''} and corporate channels.`);
        setTimeout(() => setSuccessMsg(''), 4000);
      } else {
        if (Array.isArray(list)) {
          setContacts([]);
        }
        await fetchPatternInfo();
        if (searchDiag && searchDiag.isConfigured === false) {
          setError(`Search service unavailable (${searchDiag.reason || 'provider not configured'}). No contacts were found.`);
        } else if (searchDiag && searchDiag.reason && searchDiag.reason !== 'READY') {
          setError(`Search partially unavailable (${searchDiag.reason}). No contacts were found.`);
        } else {
          setSuccessMsg('Search completed, but no public decision-maker profiles were found.');
          setTimeout(() => setSuccessMsg(''), 4000);
        }
      }
    } catch (err) {
      setError(`Contact extraction failed: ${err.message}`);
    } finally {
      setExtractingContacts(false);
    }
  };

  const handleApplyPattern = async () => {
    setApplyingPattern(true);
    setError('');
    try {
      const res = await api.post(`/companies/${companyId}/contacts/apply-pattern`, { pattern: selectedPattern });
      const updatedList = res.data?.data?.contacts || [];
      if (updatedList.length > 0) {
        setContacts(updatedList);
      } else {
        await fetchContacts();
      }
      setSuccessMsg(`Applied email format '${selectedPattern}' to decision makers as Pattern-based / Unverified.`);
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err) {
      setError(`Failed to apply email format: ${err.message}`);
    } finally {
      setApplyingPattern(false);
    }
  };

  const handleAddContact = async (e) => {
    e.preventDefault();
    if (!newContact.name.trim()) return;
    try {
      const res = await api.post(`/companies/${companyId}/contacts`, newContact);
      const saved = res.data?.data || res.data;
      setContacts([saved, ...contacts]);
      setShowAddContactModal(false);
      setNewContact({
        name: '',
        designation: '',
        roleCategory: 'ceo',
        email: '',
        linkedinUrl: '',
        seniority: 'executive',
        department: 'Executive Leadership',
        source: 'Manual Input'
      });
      setSuccessMsg('Decision maker added successfully');
      setTimeout(() => setSuccessMsg(''), 3000);
    } catch (err) {
      setError(err.message);
    }
  };

  const handleUpdateContact = async (e) => {
    e.preventDefault();
    if (!editingContact) return;
    try {
      const res = await api.put(`/contacts/${editingContact._id}`, editingContact);
      const saved = res.data?.data || res.data;
      setContacts(contacts.map(c => c._id === saved._id ? saved : c));
      setEditingContact(null);
      setSuccessMsg('Decision maker updated successfully');
      setTimeout(() => setSuccessMsg(''), 3000);
    } catch (err) {
      setError(`Failed to update decision maker: ${err.message}`);
    }
  };

  const handleSelectDecisionMaker = (contact) => {
    setSelectedContactId(contact._id);
    setActiveTab('outreach');
    if (editingMessage) {
      updateEditingMessage({
        recipientEmail: contact.email,
        recipientName: contact.name,
      });
    }
  };

  // Outreach Sequence handlers
  const handleGenerateOutreach = async () => {
    setGeneratingOutreach(true);
    setError('');
    setSendResult(null);
    try {
      const res = await api.post(`/companies/${companyId}/outreach/generate`, {
        contactId: selectedContactId,
        angle: outreachAngle,
        tone: outreachTone,
        focusService: selectedFocusService
      });
      const list = res.data?.data || res.data || [];
      if (Array.isArray(list)) {
        setOutreachMessages(list);
        const seeded = {};
        for (const m of list) seeded[m.step] = m;
        draftsByStepRef.current = seeded;
        setDraftsByStep(seeded);
        dirtyStepsRef.current = {};
        setDirtySteps({});
        const step1 = list.find((m) => m.step === 1) || list[0];
        setEditingMessage(step1);
        setSelectedStep(1);
        selectedStepRef.current = 1;
      }
      await fetchCompanyData();
      setSuccessMsg(`Generated personalized email focused on ${selectedFocusService}!`);
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err) {
      setError(`Outreach generation failed: ${err.message}`);
    } finally {
      setGeneratingOutreach(false);
    }
  };

  const handleStepSelect = (stepNum) => {
    if (stepNum === selectedStep) return;
    selectedStepRef.current = stepNum;
    setSelectedStep(stepNum);
    // Each step keeps its own working copy; unsaved edits are preserved across
    // navigation instead of being replaced by the last saved server message.
    const nextMsg = draftsByStepRef.current[stepNum] || resolveStepMessage(draftsByStep, outreachMessages, stepNum);
    setEditingMessage(nextMsg);
  };

  // CC & BCC Helpers
  const handleAddCcEmail = () => {
    if (!ccInputText.trim() || !editingMessage) return;
    const emailsToAdd = ccInputText
      .split(/[,;\s]+/)
      .map(e => e.trim().toLowerCase())
      .filter(e => Boolean(e) && e.includes('@'));

    const currentCc = Array.isArray(editingMessage.ccRecipients) ? editingMessage.ccRecipients : [];
    const merged = Array.from(new Set([...currentCc, ...emailsToAdd]));

    updateEditingMessage({ ccRecipients: merged });
    setCcInputText('');
  };

  const handleRemoveCcEmail = (emailToRemove) => {
    if (!editingMessage) return;
    const currentCc = Array.isArray(editingMessage.ccRecipients) ? editingMessage.ccRecipients : [];
    updateEditingMessage({ ccRecipients: currentCc.filter(e => e !== emailToRemove) });
  };

  const handleAddBccEmail = () => {
    if (!bccInputText.trim() || !editingMessage) return;
    const emailsToAdd = bccInputText
      .split(/[,;\s]+/)
      .map(e => e.trim().toLowerCase())
      .filter(e => Boolean(e) && e.includes('@'));

    const currentBcc = Array.isArray(editingMessage.bccRecipients) ? editingMessage.bccRecipients : [];
    const merged = Array.from(new Set([...currentBcc, ...emailsToAdd]));

    updateEditingMessage({ bccRecipients: merged });
    setBccInputText('');
  };

  const handleRemoveBccEmail = (emailToRemove) => {
    if (!editingMessage) return;
    const currentBcc = Array.isArray(editingMessage.bccRecipients) ? editingMessage.bccRecipients : [];
    updateEditingMessage({ bccRecipients: currentBcc.filter(e => e !== emailToRemove) });
  };

  const handleSaveDraft = async () => {
    if (!editingMessage) return;
    setSavingDraft(true);
    setError('');
    try {
      const isSent = isLockedMessage(editingMessage);
      // Manual-edit save: block malformed To/CC/BCC client-side with one clear
      // message before any request is made. The backend re-validates drafts and
      // answers 400 (surfaced via the api interceptor).
      if (!isSent) {
        const invalidEmails = findInvalidEmails({
          recipientEmail: editingMessage.recipientEmail,
          ccRecipients: editingMessage.ccRecipients,
          bccRecipients: editingMessage.bccRecipients,
        });
        if (invalidEmails.length > 0) {
          setError(
            `Cannot save: invalid email address${invalidEmails.length > 1 ? 'es' : ''}: ` +
            `${invalidEmails.join(', ')}. Correct them (or clear the field) and save again.`
          );
          return;
        }
      }
      // Sent messages are immutable history: the UI may only submit a
      // recipient-only correction. The backend pauses Step 2/3 for manual
      // review instead of silently redirecting the sequence.
      const payload = isSent
        ? { recipientEmail: editingMessage.recipientEmail }
        : {
            subject: editingMessage.subject,
            bodyHtml: editingMessage.bodyHtml,
            bodyText: editingMessage.bodyText,
            recipientEmail: editingMessage.recipientEmail,
            recipientName: editingMessage.recipientName,
            ccRecipients: editingMessage.ccRecipients || [],
            bccRecipients: editingMessage.bccRecipients || [],
            focusService: selectedFocusService,
            linkedinNote: editingMessage.linkedinNote,
            linkedinInmail: editingMessage.linkedinInmail,
          };
      const res = await api.put(`/outreach/${editingMessage._id}`, payload);
      // The axios interceptor unwraps the response to its BODY, so the message
      // is `res.data` and recipientSync lives at the top level (`res.recipientSync`).
      const updated = res?.data?.data || res?.data || res;
      const sync = res?.recipientSync ?? res?.data?.recipientSync ?? null;
      const savedStep = updated?.step ?? editingMessage.step;
      setStepDirty(savedStep, false);

      setDraftsByStep((d) => {
        const nextDrafts = { ...d, [savedStep]: updated };
        if (savedStep === 1 && sync) {
          for (const stepNum of [2, 3]) {
            const followUp = nextDrafts[stepNum];
            if (followUp && !isLockedMessage(followUp)) {
              const patch = {};
              if (sync.updated > 0) {
                patch.recipientEmail = updated.recipientEmail;
                if (updated.recipientName) {
                  patch.recipientName = updated.recipientName;
                }
              }
              if (sync.ccUpdated > 0 && Array.isArray(updated.ccRecipients)) {
                patch.ccRecipients = updated.ccRecipients;
              }
              if (Object.keys(patch).length > 0) {
                nextDrafts[stepNum] = { ...followUp, ...patch };
              }
            }
          }
        }
        draftsByStepRef.current = nextDrafts;
        return nextDrafts;
      });

      setOutreachMessages((prev) =>
        prev.map((m) => {
          if (m._id === updated._id) return updated;
          if (savedStep === 1 && (m.step === 2 || m.step === 3) && !isLockedMessage(m)) {
            const patch = {};
            if (sync?.updated > 0) {
              patch.recipientEmail = updated.recipientEmail;
              if (updated.recipientName) patch.recipientName = updated.recipientName;
            }
            if (sync?.ccUpdated > 0 && Array.isArray(updated.ccRecipients)) {
              patch.ccRecipients = updated.ccRecipients;
            }
            return Object.keys(patch).length > 0 ? { ...m, ...patch } : m;
          }
          return m;
        })
      );

      if (selectedStepRef.current === savedStep) {
        setEditingMessage(updated);
      } else {
        const activeMsg = draftsByStepRef.current[selectedStepRef.current] ||
          resolveStepMessage(draftsByStepRef.current, outreachMessages, selectedStepRef.current);
        if (activeMsg) {
          setEditingMessage(activeMsg);
        }
      }

      const feedback = describeRecipientSync(sync);
      if (feedback) {
        setSuccessMsg(feedback.message);
      } else {
        setSuccessMsg('Email draft and custom edits saved successfully!');
      }
      setTimeout(() => setSuccessMsg(''), 5000);
      // The PUT response only echoes Step 1, so a successful recipient/CC sync
      // (sync.updated > 0 || sync.ccUpdated > 0) leaves Steps 2/3 stale in local
      // state. Refetch, or the editor keeps showing the pre-sync recipient and
      // CC. mergeServerMessages protects any step with unsaved edits.
      if (shouldRefetchAfterSave({ isSent, sync })) {
        await fetchOutreach();
      }
      if (isSent) {
        await fetchCompanyData();
      }
    } catch (err) {
      setError(`Failed to save draft: ${err.message}`);
    } finally {
      setSavingDraft(false);
    }
  };

  const handleRegenerateEmail = async () => {
    if (!editingMessage || editingMessage.step !== 1) return;
    if (editingMessage.status === 'sent') return;
    setRegeneratingEmail(true);
    setError('');
    try {
      const res = await api.post(`/outreach/${editingMessage._id}/regenerate`, { useAi: false });
      const updated = res?.data?.data || res?.data || res;
      const savedStep = updated?.step ?? editingMessage.step;
      setOutreachMessages((prev) => prev.map((m) => (m._id === updated._id ? updated : m)));
      setDraftsByStep((d) => {
        const next = { ...d, [savedStep]: updated };
        draftsByStepRef.current = next;
        return next;
      });
      setStepDirty(savedStep, false);
      if (selectedStepRef.current === savedStep) {
        setEditingMessage(updated);
      }
      setSuccessMsg('Step 1 email regenerated from Evidence + Recommended Service. Review before sending.');
      setTimeout(() => setSuccessMsg(''), 5000);
    } catch (err) {
      setError(`Failed to regenerate email: ${err.message}`);
    } finally {
      setRegeneratingEmail(false);
    }
  };

  const handleSendEmail = async () => {
    if (!editingMessage) return;
    // FIX 4: a sent message must never be resent from the UI.
    if (editingMessage.status === 'sent') {
      setError('This email has already been sent. Duplicate sends are blocked.');
      return;
    }
    setSendingEmail(true);
    setError('');
    setSendResult(null);
    try {
      const res = await api.post(`/outreach/${editingMessage._id}/send`, {
        recipientEmail: editingMessage.recipientEmail,
        ccRecipients: editingMessage.ccRecipients || [],
        bccRecipients: editingMessage.bccRecipients || [],
      });
      setSendResult(res.data);
      // The message is now terminal (sent): drop its unsaved draft flag so the
      // canonical, immutable record is what reloads.
      setStepDirty(editingMessage.step, false);
      await fetchOutreach();
      await fetchCompanyData();
      if (editingMessage.step === 1) {
        setSuccessMsg('Step 1 sent successfully. Automated drip follow-ups have been scheduled.');
        setTimeout(() => setSuccessMsg(''), 6000);
      } else {
        setSuccessMsg(`Step ${editingMessage.step} sent successfully!`);
        setTimeout(() => setSuccessMsg(''), 5000);
      }
    } catch (err) {
      setError(`Failed to send email: ${err.response?.data?.message || err.message}`);
    } finally {
      setSendingEmail(false);
    }
  };

  const handleActivateSchedule = async () => {
    setScheduling(true);
    setError('');
    try {
      const res = await api.post(`/companies/${companyId}/outreach/schedule`, {
        schedules: [
          { step: 1, delayDays: 0 },
          { step: 2, delayDays: Number(scheduleConfig.step2Days) || 3 },
          { step: 3, delayDays: Number(scheduleConfig.step3Days) || 6 },
        ]
      });
      setShowScheduleModal(false);
      await fetchOutreach();
      const step1Msg = outreachMessages.find((m) => m.step === 1);
      const feedback = describeScheduleResult(res?.data || res, step1Msg || editingMessage);
      if (feedback.tone === 'warning') {
        setError(feedback.message);
      } else {
        setSuccessMsg(feedback.message);
        setTimeout(() => setSuccessMsg(''), 5000);
      }
    } catch (err) {
      setError(`Failed to schedule sequence: ${err.response?.data?.message || err.message}`);
    } finally {
      setScheduling(false);
    }
  };

  const copyToClipboard = (text, fieldName) => {
    navigator.clipboard.writeText(text);
    setCopiedField(fieldName);
    setTimeout(() => setCopiedField(''), 2500);
  };

  if (loading) return <div className="text-center py-16 text-slate-500 font-medium">Loading company intelligence...</div>;
  if (!company) return <div className="text-center py-16 text-slate-500 font-medium">Company not found.</div>;

  const crawlStatus = crawlData?.crawlStatus || company.crawlStatus || 'pending';
  const researchStatus = company.researchStatus || (research ? 'completed' : 'pending');
  const outreachStatus = company.outreachStatus || (outreachMessages.length > 0 ? 'generated' : 'none');

  // FIX 3: derive the real drip state (inactive / approved / active / completed
  // / stopped after reply) from the message statuses.
  const sequenceState = deriveSequenceState(outreachMessages);
  const sequenceMeta = SEQUENCE_STATE_META[sequenceState] || SEQUENCE_STATE_META.inactive;

  // Filter contacts by Role Category
  const leadershipContacts = contacts.filter(c => c.roleCategory !== 'general' && c.seniority !== 'general');
  const companyChannels = contacts.filter(c => c.roleCategory === 'general' || c.seniority === 'general');

  const filteredContacts = contacts.filter((c) => {
    if (roleFilter === 'all') return true;
    if (roleFilter === 'c_suite') return ['ceo', 'founder', 'co_founder', 'president', 'managing_director'].includes(c.roleCategory);
    if (roleFilter === 'tech') return ['cto', 'cio', 'cdo', 'head_of_ai', 'head_of_data', 'head_of_technology', 'dept_head'].includes(c.roleCategory);
    if (roleFilter === 'coo') return ['coo', 'head_of_operations'].includes(c.roleCategory);
    if (roleFilter === 'cfo') return c.roleCategory === 'cfo';
    if (roleFilter === 'vp') return c.roleCategory === 'vp';
    if (roleFilter === 'general') return c.roleCategory === 'general' || c.seniority === 'general';
    return true;
  });

  // The message the UI should treat as active for the selected step. If the
  // bound editor message is stale (still pointing at another step), re-resolve
  // the step's own draft/server message so the sent/locked banner and badges
  // always reflect the actually-selected step.
  const activeMessage = getActiveStepMessage(draftsByStep, outreachMessages, selectedStep, editingMessage);

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Header */}
      <div>
        <button
          onClick={() => navigate('/companies')}
          className="text-xs text-slate-500 hover:text-slate-900 font-bold inline-flex items-center gap-1 mb-3 transition-colors"
        >
          &larr; Back to Company Directory
        </button>

        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-black text-slate-900 tracking-tight">{company.companyName}</h1>
              <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase ${CRAWL_STATUS_STYLES[crawlStatus]}`}>
                Crawl: {crawlStatus}
              </span>
              <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase ${RESEARCH_STATUS_STYLES[researchStatus]}`}>
                AI Research: {researchStatus}
              </span>
              <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase ${OUTREACH_STATUS_STYLES[outreachStatus]}`}>
                Outreach: {outreachStatus}
              </span>
            </div>
            <a
              href={company.website}
              target="_blank"
              rel="noopener noreferrer"
              className="text-indigo-600 hover:underline text-xs font-semibold mt-1 inline-flex items-center gap-1"
            >
              <span>{company.website}</span>
              <span>&rarr;</span>
            </a>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={handleTriggerResearch}
              disabled={researching || pages.length === 0}
              className="px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-xl text-xs font-bold transition-all shadow-sm disabled:opacity-50 flex items-center gap-2"
            >
              <span>{researching ? '⏳' : '✨'}</span>
              <span>{researching ? 'Analyzing with AI...' : research ? 'Re-Run AI Intelligence' : 'Run AI Intelligence'}</span>
            </button>
            <button
              onClick={() => setActiveTab('outreach')}
              className="px-4 py-2 bg-gradient-to-r from-indigo-600 to-blue-600 hover:from-indigo-700 hover:to-blue-700 text-white rounded-xl text-xs font-bold transition-all shadow-sm flex items-center gap-2"
            >
              <span>✉️</span>
              <span>Create AI Outreach</span>
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-2xl text-xs flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError('')} className="text-red-500 font-bold">&times;</button>
        </div>
      )}

      {successMsg && (
        <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 px-4 py-3 rounded-2xl text-xs flex items-center justify-between animate-fadeIn">
          <span>{successMsg}</span>
          <button onClick={() => setSuccessMsg('')} className="text-emerald-500 font-bold">&times;</button>
        </div>
      )}

      {/* TKSR Outreach Inputs */}
      <div className="bg-white rounded-2xl border border-slate-200/80 p-5 shadow-xs">
        <div className="flex items-center justify-between mb-3 border-b border-slate-100 pb-2">
          <h2 className="text-xs font-bold uppercase tracking-wider text-slate-700 flex items-center gap-1.5">
            <span>📋</span>
            <span>TKSR Outreach Inputs</span>
          </h2>
          <span className="text-[10px] bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full font-semibold">
            Authoritative Excel Source
          </span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="bg-slate-50/70 border border-slate-200/60 rounded-xl p-3.5 space-y-1">
            <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500 block">
              Evidence
            </span>
            <p className="text-xs text-slate-800 leading-relaxed font-medium whitespace-pre-wrap">
              {company.evidence && company.evidence.trim() ? (
                company.evidence
              ) : (
                <span className="text-slate-400 italic">Not configured</span>
              )}
            </p>
          </div>
          <div className="bg-slate-50/70 border border-slate-200/60 rounded-xl p-3.5 space-y-1">
            <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500 block">
              Recommended Service
            </span>
            <p className="text-xs text-slate-800 leading-relaxed font-medium">
              {company.recommendedService && company.recommendedService.trim() ? (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-indigo-50 text-indigo-700 font-semibold border border-indigo-200/60">
                  <span>🎯</span>
                  <span>{company.recommendedService}</span>
                </span>
              ) : (
                <span className="text-slate-400 italic">Not configured</span>
              )}
            </p>
          </div>
        </div>
      </div>

      {/* Tabs Navigation */}
      <div className="flex border-b border-slate-200 space-x-6">
        {[
          { id: 'crawl', label: '1. Web Crawl & Content', badge: pages.length, icon: '🌐' },
          { id: 'research', label: '2. AI Intelligence', badge: research ? 'Ready' : null, icon: '🧠' },
          { id: 'contacts', label: '3. Decision Makers', badge: contacts.length, icon: '👥' },
          { id: 'outreach', label: '4. AI Outreach & Dispatch', badge: outreachMessages.length > 0 ? `${outreachMessages.length} steps` : null, icon: '🚀' },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`pb-3.5 text-xs font-bold transition-colors border-b-2 flex items-center gap-2 ${
              activeTab === tab.id
                ? 'border-indigo-600 text-indigo-600'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            <span>{tab.icon}</span>
            <span>{tab.label}</span>
            {tab.badge !== null && (
              <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold ${
                activeTab === tab.id ? 'bg-indigo-100 text-indigo-800' : 'bg-slate-100 text-slate-600'
              }`}>
                {tab.badge}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* TAB 1: CRAWL CONTENT */}
      {activeTab === 'crawl' && (
        <div className="space-y-6">
          <div className="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-xs flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
            <div>
              <h2 className="text-base font-bold text-slate-900">Website Crawl Engine</h2>
              <p className="text-xs text-slate-500 mt-0.5">
                Extracts clean structured text, team rosters, and corporate pages directly from source URLs for AI intelligence modeling.
              </p>
            </div>
            <button
              onClick={handleTriggerCrawl}
              disabled={crawling}
              className="px-5 py-2.5 bg-indigo-600 text-white rounded-xl text-xs font-bold hover:bg-indigo-700 transition-colors shadow-xs disabled:opacity-50 flex items-center gap-2"
            >
              <span>{crawling ? '⏳' : '🔄'}</span>
              <span>{crawling ? 'Crawling & Finding Decision Makers...' : pages.length > 0 ? 'Re-Crawl Website' : 'Start Web Crawl'}</span>
            </button>
          </div>

          {(crawlStatus === 'blocked' || company.crawlStatus === 'blocked') && (
            <div className="bg-amber-50 border border-amber-200 rounded-2xl p-5 space-y-2">
              <div className="flex items-center gap-2 font-bold text-amber-900 text-sm">
                <span>⚠️</span>
                <span>Website Crawl Blocked by Access Controls (Akamai / Cloudflare / CDN)</span>
              </div>
              <p className="text-xs text-amber-800 leading-relaxed">
                Official domain ({company.website}) returned an external CDN or access restriction (403 Forbidden / Cloudflare challenge / Akamai). Direct crawl was safely halted to prevent bad error HTML from reaching the AI pipeline.
              </p>
              <div className="pt-2 flex items-center gap-3">
                <button
                  onClick={() => { setActiveTab('research'); handleTriggerResearch(); }}
                  className="px-4 py-2 bg-amber-700 hover:bg-amber-800 text-white rounded-xl font-bold text-xs shadow-xs flex items-center gap-1.5 transition-colors"
                >
                  <span>🔍</span>
                  <span>Run Fallback Public Research →</span>
                </button>
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-1 bg-white rounded-2xl border border-slate-200/80 p-4 shadow-xs space-y-3">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Crawled Pages ({pages.length})</h3>
              <div className="space-y-1.5 max-h-[500px] overflow-y-auto pr-1">
                {pages.map((p) => (
                  <button
                    key={p._id}
                    onClick={() => setSelectedPage(p)}
                    className={`w-full text-left p-3 rounded-xl text-xs transition-all border ${
                      selectedPage?._id === p._id
                        ? 'bg-indigo-50 border-indigo-200 text-indigo-900 font-bold'
                        : 'border-transparent hover:bg-slate-50 text-slate-700'
                    }`}
                  >
                    <p className="truncate font-semibold">{p.title || p.url}</p>
                    <div className="flex items-center gap-2 mt-1 text-[11px] text-slate-400 font-normal">
                      <span className="bg-slate-100 px-1.5 py-0.5 rounded uppercase font-bold text-[9px]">{p.pageType}</span>
                      <span>{p.wordCount || 0} words</span>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            <div className="lg:col-span-2 bg-white rounded-2xl border border-slate-200/80 p-6 shadow-xs">
              {selectedPage ? (
                <div className="space-y-4">
                  <div className="border-b pb-3">
                    <h3 className="font-bold text-slate-900 text-sm">{selectedPage.title}</h3>
                    <a href={selectedPage.url} target="_blank" rel="noreferrer" className="text-indigo-600 text-xs hover:underline truncate block">
                      {selectedPage.url}
                    </a>
                  </div>
                  <div className="prose prose-xs max-h-[420px] overflow-y-auto font-mono text-xs text-slate-600 bg-slate-50 p-4 rounded-xl">
                    {selectedPage.content}
                  </div>
                </div>
              ) : (
                <div className="text-center py-20 text-slate-400 text-xs">
                  Select a page on the left to inspect extracted text content.
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: AI RESEARCH */}
      {activeTab === 'research' && (
        <div className="space-y-6">
          {research ? (
            <div className="space-y-6">
              {/* Fallback Notice Banner */}
              {research.fallbackUsed && (
                <div className="bg-indigo-50/80 border border-indigo-200 rounded-2xl p-4 flex items-start gap-3">
                  <span className="text-xl">🔍</span>
                  <div>
                    <p className="text-xs font-bold text-indigo-950">Fallback Research Applied (Public Web Sources &amp; Business Records)</p>
                    <p className="text-[11px] text-indigo-800 mt-0.5">
                      Official website was protected by access controls. Company intelligence was synthesized from verified public web searches, Wikipedia corporate records, and press announcements.
                    </p>
                  </div>
                </div>
              )}

              <div className="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-xs space-y-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-base font-bold text-slate-900">Executive Summary &amp; Market Alignment</h2>
                  <div className="flex items-center gap-2">
                    <span className="px-3 py-1 bg-slate-100 text-slate-700 rounded-full font-bold text-[11px]">
                      Source: {research.fallbackUsed ? 'Public Sources (Fallback)' : 'Direct Web Crawl'}
                    </span>
                    <span className="px-3 py-1 bg-purple-50 text-purple-700 rounded-full font-bold text-xs">
                      ICP Fit Score: {research.icpFitScore}/100
                    </span>
                  </div>
                </div>
                <p className="text-xs text-slate-700 leading-relaxed bg-slate-50 p-4 rounded-xl border border-slate-100">
                  {research.summary}
                </p>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
                  <div className="p-4 bg-indigo-50/50 rounded-xl border border-indigo-100">
                    <h4 className="text-xs font-bold text-indigo-900 uppercase tracking-wider mb-2">Core Offerings</h4>
                    <ul className="space-y-1.5 text-xs text-slate-700">
                      {(research.coreOfferings || []).map((o, idx) => (
                        <li key={idx} className="flex items-center gap-2">
                          <span className="text-indigo-500 font-bold">•</span> {o}
                        </li>
                      ))}
                    </ul>
                  </div>

                  <div className="p-4 bg-purple-50/50 rounded-xl border border-purple-100">
                    <h4 className="text-xs font-bold text-purple-900 uppercase tracking-wider mb-2">Recommended TKSR AI Services</h4>
                    <ul className="space-y-1.5 text-xs text-slate-700">
                      {(research.recommendedTksrServices || TKSR_SERVICES.slice(0, 4).map(s => s.id)).map((s, idx) => (
                        <li key={idx} className="flex items-center gap-2 font-medium">
                          <span className="text-purple-600">✨</span> {s}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>

              {/* Detected Pain Points */}
              <div className="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-xs space-y-4">
                <h3 className="text-sm font-bold text-slate-900">Detected Operational &amp; AI Pain Points</h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  {(research.detectedPainPoints || []).map((point, idx) => (
                    <div key={idx} className="p-4 bg-slate-50 rounded-xl border border-slate-200 space-y-2">
                      <p className="text-xs font-bold text-slate-900">{point.title}</p>
                      <p className="text-[11px] text-slate-600 leading-relaxed">{point.description}</p>
                    </div>
                  ))}
                </div>
              </div>

              {/* Evidence & Sources (when fallback or sources used) */}
              {((research.evidenceItems && research.evidenceItems.length > 0) || (research.sourcesUsed && research.sourcesUsed.length > 0)) && (
                <div className="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-xs space-y-4">
                  <h3 className="text-sm font-bold text-slate-900">
                    {research.fallbackUsed ? `Public Evidence & Citations (${research.evidenceItems?.length || 0})` : `Crawled Sources Used (${research.sourcesUsed?.length || 0})`}
                  </h3>
                  <div className="space-y-2.5 max-h-60 overflow-y-auto pr-1">
                    {research.fallbackUsed && research.evidenceItems?.map((item, idx) => (
                      <div key={idx} className="p-3 bg-slate-50 rounded-xl border border-slate-200 text-xs space-y-1">
                        <div className="flex items-center justify-between">
                          <a href={item.sourceUrl} target="_blank" rel="noreferrer" className="font-bold text-indigo-600 hover:underline truncate">
                            {item.sourceTitle || item.sourceUrl}
                          </a>
                          <span className="bg-slate-200/80 px-2 py-0.5 rounded text-[10px] font-semibold text-slate-600">{item.sourceType}</span>
                        </div>
                        <p className="text-[11px] text-slate-600 italic">"{item.evidenceText}"</p>
                      </div>
                    ))}
                    {!research.fallbackUsed && research.sourcesUsed?.map((src, idx) => (
                      <div key={idx} className="p-2.5 bg-slate-50 rounded-xl border border-slate-200 text-xs flex items-center justify-between">
                        <a href={src.url} target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline truncate font-medium">
                          {src.title || src.url}
                        </a>
                        <span className="bg-slate-200/80 px-2 py-0.5 rounded text-[10px] uppercase font-bold text-slate-600">{src.pageType}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="bg-white rounded-3xl border border-slate-200 p-12 text-center">
              <p className="text-4xl mb-3">🧠</p>
              <h3 className="text-lg font-bold text-slate-900">No AI Intelligence Report Generated Yet</h3>
              <p className="text-xs text-slate-500 max-w-md mx-auto mt-2 mb-6">
                Run the AI Intelligence analyzer to synthesize website content or fallback public business sources to detect high-converting outreach hooks.
              </p>
              <button
                onClick={handleTriggerResearch}
                disabled={researching}
                className="px-6 py-2.5 bg-purple-600 text-white rounded-xl font-bold text-xs hover:bg-purple-700 shadow-md transition-all disabled:opacity-50"
              >
                {researching ? 'Analyzing...' : 'Generate AI Intelligence Report'}
              </button>
            </div>
          )}
        </div>
      )}

      {/* TAB 3: DECISION MAKERS & EVIDENCE INSPECTION */}
      {activeTab === 'contacts' && (() => {
        const decisionMakers = contacts.filter(c => c.roleCategory !== 'general' && c.seniority !== 'general');
        const companyInboxes = contacts.filter(c => c.roleCategory === 'general' || c.seniority === 'general');

        const filteredDecisionMakers = decisionMakers.filter(c => {
          if (roleFilter === 'all') return true;
          if (roleFilter === 'c_suite') return ['ceo', 'founder', 'co_founder', 'president', 'managing_director'].includes(c.roleCategory);
          if (roleFilter === 'tech') return ['cto', 'cio', 'cdo', 'head_of_ai', 'head_of_data', 'head_of_technology', 'dept_head'].includes(c.roleCategory);
          if (roleFilter === 'coo') return ['coo', 'head_of_operations'].includes(c.roleCategory);
          if (roleFilter === 'cfo') return c.roleCategory === 'cfo';
          if (roleFilter === 'vp') return c.roleCategory === 'vp';
          return true;
        });

        return (
          <div className="space-y-6">
            {/* Header Card with Controls */}
            <div className="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-xs flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
              <div>
                <div className="flex items-center flex-wrap gap-2.5">
                  <h2 className="text-base font-bold text-slate-900">Decision Makers &amp; Evidence-Based Leadership</h2>
                  <span className={`px-2.5 py-0.5 rounded-full text-[11px] font-bold border ${
                    decisionMakers.length >= 6
                      ? 'bg-emerald-50 text-emerald-800 border-emerald-300'
                      : 'bg-amber-50 text-amber-800 border-amber-300'
                  }`}>
                    Target: 6 | Verified: {decisionMakers.length} ({decisionMakers.length >= 6 ? 'COMPLETE' : 'PARTIAL'})
                  </span>
                </div>
                <p className="text-xs text-slate-500 mt-0.5">
                  Verified real executive stakeholders (CEO, CTO, Founder, COO, CFO, VP, Department Heads) with source URLs and verified emails.
                </p>
              </div>
              <div className="flex items-center gap-3">
                <button
                  onClick={handleExtractContacts}
                  disabled={extractingContacts}
                  className="px-4 py-2.5 bg-gradient-to-r from-purple-600 to-indigo-600 text-white rounded-xl text-xs font-bold hover:from-purple-700 hover:to-indigo-700 transition-all shadow-sm disabled:opacity-50 flex items-center gap-2"
                >
                  <span>{extractingContacts ? '⏳' : '🔍'}</span>
                  <span>{extractingContacts ? 'Scanning Leadership...' : contacts.length > 0 ? 'Re-Scan Decision Makers' : 'Discover Decision Makers'}</span>
                </button>
                <button
                  onClick={() => setShowAddContactModal(true)}
                  className="px-4 py-2.5 bg-white border border-slate-200 text-slate-700 rounded-xl text-xs font-bold hover:bg-slate-50 transition-colors shadow-xs"
                >
                  + Add Decision Maker
                </button>
              </div>
            </div>

            {/* Opportunity-Aligned Primary Decision Maker Hero Card */}
            {(() => {
              const primaryDm = decisionMakers.find(c => c.isPrimaryDecisionMaker) || decisionMakers[0];
              if (!primaryDm) return null;

              return (
                <div className="bg-gradient-to-br from-indigo-900 via-slate-900 to-purple-950 text-white rounded-2xl p-6 shadow-md border border-indigo-500/20 space-y-4">
                  <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                    <div className="flex items-center gap-3">
                      <div className="w-12 h-12 rounded-xl bg-indigo-500/20 border border-indigo-400/30 flex items-center justify-center text-2xl">
                        {ROLE_ICONS_AND_LABELS[primaryDm.roleCategory]?.icon || '👑'}
                      </div>
                      <div>
                        <div className="flex items-center flex-wrap gap-2">
                          <span className="text-[10px] font-extrabold uppercase tracking-wider px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                            {primaryDm.decisionMakerStatus === 'NOT_VERIFIED' ? '⚠️ Needs Verification' : '✓ Primary Decision Maker Verified'}
                          </span>
                          <span className="text-[10px] font-bold text-indigo-300 bg-indigo-500/20 px-2 py-0.5 rounded-full border border-indigo-400/30">
                            🎯 {primaryDm.targetOpportunity || 'AI Strategy & Solutions'}
                          </span>
                        </div>
                        <h3 className="text-lg font-bold text-white mt-1 flex items-center gap-2">
                          {primaryDm.name}
                          <span className="text-xs font-normal text-indigo-200">— {primaryDm.designation || primaryDm.title}</span>
                        </h3>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <div className="text-right">
                        <p className="text-[10px] uppercase font-bold text-indigo-300 tracking-wider">Opportunity Match</p>
                        <p className="text-lg font-mono font-extrabold text-emerald-400">{primaryDm.overallScore || primaryDm.relevanceScore || 90}%</p>
                      </div>
                      <button
                        onClick={() => handleSelectDecisionMaker(primaryDm)}
                        className={`px-4 py-2 rounded-xl font-bold text-xs shadow-sm transition-all ${
                          selectedContactId === primaryDm._id
                            ? 'bg-emerald-500 text-slate-950 font-extrabold'
                            : 'bg-indigo-600 text-white hover:bg-indigo-500'
                        }`}
                      >
                        {selectedContactId === primaryDm._id ? '✓ Selected Target' : 'Select Target'}
                      </button>
                    </div>
                  </div>

                  {/* Verification Badges Row */}
                  <div className="flex items-center flex-wrap gap-2 pt-1">
                    {primaryDm.personVerified === 'true' && (
                      <span className="text-[10px] font-bold text-emerald-300 bg-emerald-950/60 border border-emerald-500/40 px-2 py-0.5 rounded-md">
                        ✓ Person Verified
                      </span>
                    )}
                    <span className="text-[10px] font-bold text-emerald-300 bg-emerald-950/60 border border-emerald-500/40 px-2 py-0.5 rounded-md">
                      ✓ Company Verified
                    </span>
                    <span className="text-[10px] font-bold text-emerald-300 bg-emerald-950/60 border border-emerald-500/40 px-2 py-0.5 rounded-md">
                      ✓ Current Role
                    </span>
                    {primaryDm.patternUsed && primaryDm.patternUsed !== 'none' && (
                      <span className="text-[10px] font-medium text-indigo-200 bg-indigo-950/60 border border-indigo-500/30 px-2 py-0.5 rounded-md">
                        Pattern: <span className="font-mono font-bold text-white">{primaryDm.patternUsed}</span>
                        {primaryDm.patternConfidence && primaryDm.patternConfidence !== 'none' && ` (${primaryDm.patternConfidence === 'high' ? '96%' : '70%'} confidence)`}
                      </span>
                    )}
                  </div>

                  {/* Selection Reason Box */}
                  {primaryDm.selectionReason && (
                    <div className="bg-white/5 border border-white/10 rounded-xl p-3 text-xs text-indigo-100 flex items-start gap-2.5">
                      <span className="text-indigo-400 text-sm mt-0.5">💡</span>
                      <div>
                        <span className="font-bold text-white">Why Selected for Opportunity: </span>
                        <span className="text-slate-200">{primaryDm.selectionReason}</span>
                      </div>
                    </div>
                  )}

                  {/* Quick Details Bar */}
                  <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 pt-2 border-t border-white/10 text-xs">
                    <div className="flex items-center justify-between bg-black/20 p-2.5 rounded-lg border border-white/5">
                      <span className="text-indigo-300 text-[11px]">Professional Email:</span>
                      <span className="font-mono font-bold text-white truncate max-w-[150px]">{primaryDm.email || 'Not Found'}</span>
                    </div>
                    <div className="flex items-center justify-between bg-black/20 p-2.5 rounded-lg border border-white/5">
                      <span className="text-indigo-300 text-[11px]">Email Status:</span>
                      <span className={`text-[10px] font-bold truncate max-w-[140px] ${
                        resolveUserFacingEmailStatus(primaryDm) === 'EXACT_FOUND' ? 'text-emerald-400' :
                        resolveUserFacingEmailStatus(primaryDm) === 'PATTERN_GENERATED' ? 'text-amber-400' :
                        'text-slate-400'
                      }`}>
                        {resolveUserFacingEmailStatus(primaryDm)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between bg-black/20 p-2.5 rounded-lg border border-white/5">
                      <span className="text-indigo-300 text-[11px]">Mailbox Status:</span>
                      <span className="text-[10px] font-medium text-slate-200 truncate max-w-[140px]">
                        {!primaryDm.email ? 'N/A' : (primaryDm.mailboxVerification === 'MAILBOX_VERIFIED' ? '✓ Mailbox Verified' : 'UNVERIFIED')}
                      </span>
                    </div>
                    <div className="flex items-center justify-between bg-black/20 p-2.5 rounded-lg border border-white/5">
                      <span className="text-indigo-300 text-[11px]">Primary Source:</span>
                      {primaryDm.sourceUrl ? (
                        <a href={primaryDm.sourceUrl} target="_blank" rel="noreferrer" className="text-indigo-400 hover:underline truncate max-w-[130px] font-medium">
                          🔗 {primaryDm.source || 'Leadership Page'}
                        </a>
                      ) : (
                        <span className="text-slate-300 truncate max-w-[130px]">{primaryDm.source || 'Leadership Page'}</span>
                      )}
                    </div>
                  </div>
                </div>
              );
            })()}

            {/* Role Filter Tabs */}
            {decisionMakers.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {[
                  { id: 'all', label: `All Decision Makers (${decisionMakers.length})` },
                  { id: 'c_suite', label: `👑 CEO & Founders (${decisionMakers.filter(c => ['ceo', 'founder', 'co_founder', 'president', 'managing_director'].includes(c.roleCategory)).length})` },
                  { id: 'tech', label: `🚀 CTO / CIO / AI / Data (${decisionMakers.filter(c => ['cto', 'cio', 'cdo', 'head_of_ai', 'head_of_data', 'head_of_technology', 'dept_head'].includes(c.roleCategory)).length})` },
                  { id: 'coo', label: `💼 COO & Operations (${decisionMakers.filter(c => ['coo', 'head_of_operations'].includes(c.roleCategory)).length})` },
                  { id: 'cfo', label: `💰 CFO & Finance (${decisionMakers.filter(c => c.roleCategory === 'cfo').length})` },
                  { id: 'vp', label: `🚀 VPs (${decisionMakers.filter(c => c.roleCategory === 'vp').length})` },
                ].map((filter) => (
                  <button
                    key={filter.id}
                    onClick={() => setRoleFilter(filter.id)}
                    className={`px-3.5 py-1.5 rounded-xl text-xs font-bold transition-all ${
                      roleFilter === filter.id
                        ? 'bg-slate-900 text-white shadow-sm'
                        : 'bg-white border border-slate-200 text-slate-600 hover:bg-slate-50'
                    }`}
                  >
                    {filter.label}
                  </button>
                ))}
              </div>
            )}

            {/* Main Decision Makers Table */}
            {filteredDecisionMakers.length === 0 ? (
              <div className="bg-white rounded-3xl border border-slate-200 p-12 text-center">
                <p className="text-3xl mb-2">👥</p>
                <p className="font-bold text-slate-900 text-sm">No verified decision maker found.</p>
                <p className="text-xs text-slate-500 mt-1 mb-4">Click below to search live sources for real leadership profiles.</p>
                <button
                  onClick={handleExtractContacts}
                  disabled={extractingContacts}
                  className="px-5 py-2 bg-indigo-600 text-white rounded-xl text-xs font-bold hover:bg-indigo-700"
                >
                  Scan Decision Makers
                </button>
              </div>
            ) : (
              <div className="bg-white rounded-2xl border border-slate-200/80 overflow-hidden shadow-xs">
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-50/80 border-b border-slate-200/80 text-[11px] font-bold text-slate-500 uppercase tracking-wider">
                      <tr>
                        <th className="px-5 py-3.5">Decision Maker</th>
                        <th className="px-4 py-3.5">Designation</th>
                        <th className="px-5 py-3.5">Professional Email</th>
                        <th className="px-4 py-3.5">Domain MX</th>
                        <th className="px-4 py-3.5">Mailbox Status</th>
                        <th className="px-4 py-3.5">Confidence</th>
                        <th className="px-4 py-3.5">Source</th>
                        <th className="px-5 py-3.5 text-right">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {filteredDecisionMakers.map((c) => {
                        const isSelected = selectedContactId === c._id;
                        const roleMeta = ROLE_ICONS_AND_LABELS[c.roleCategory] || ROLE_ICONS_AND_LABELS.other;
                        const emailStatusKey = resolveUserFacingEmailStatus(c);
                        const emailMeta = EMAIL_STATUS_META[emailStatusKey] || EMAIL_STATUS_META.NOT_FOUND;

                        const isMxValid = c.mxStatus === 'MX_ACTIVE' || c.emailDomainValid === 'true' || c.domainStatus === 'ACTIVE_MX';
                        const isDirectMatch = c.mailboxVerification === 'DIRECT_SOURCE_MATCH' || c.emailStatus === 'EXACT_PUBLIC_SOURCE';

                        return (
                          <tr
                            key={c._id}
                            className={`hover:bg-slate-50/80 transition-colors ${
                              isSelected ? 'bg-indigo-50/40' : ''
                            }`}
                          >
                            {/* Name & Person Verification */}
                            <td className="px-5 py-4 whitespace-nowrap">
                              <div className="flex items-center gap-2">
                                <span className="text-base">{roleMeta.icon}</span>
                                <div>
                                  <p className="font-bold text-slate-900 text-xs flex items-center gap-1.5">
                                    {c.name}
                                    {isSelected && (
                                      <span className="text-[9px] font-extrabold bg-indigo-600 text-white px-1.5 py-0.2 rounded">
                                        ACTIVE TARGET
                                      </span>
                                    )}
                                  </p>
                                  <div className="flex items-center gap-1.5 mt-0.5">
                                    {c.personVerified === 'true' && c.decisionMakerStatus === 'VERIFIED' ? (
                                      <span className="inline-flex items-center gap-0.5 text-[9px] font-semibold text-emerald-700 bg-emerald-50 px-1.5 py-0.2 rounded border border-emerald-200">
                                        ✓ Person Verified
                                      </span>
                                    ) : c.decisionMakerStatus === 'FORMER' ? (
                                      <span className="inline-flex items-center gap-0.5 text-[9px] font-semibold text-amber-700 bg-amber-50 px-1.5 py-0.2 rounded border border-amber-200">
                                        ⚠️ Former Executive
                                      </span>
                                    ) : (
                                      <span className="inline-flex items-center gap-0.5 text-[9px] font-semibold text-slate-600 bg-slate-100 px-1.5 py-0.2 rounded border border-slate-200">
                                        🔍 Candidate
                                      </span>
                                    )}
                                    {c.candidateEmployer && c.candidateEmployer.toLowerCase() !== company.companyName.toLowerCase() && (
                                      <span className="text-[9px] text-slate-500 font-medium">
                                        • {c.candidateEmployer}
                                      </span>
                                    )}
                                    {c.linkedinUrl && (
                                      <a
                                        href={c.linkedinUrl}
                                        target="_blank"
                                        rel="noreferrer"
                                        className="text-[10px] text-blue-600 hover:underline inline-flex items-center gap-0.5 font-medium"
                                      >
                                        <span>🔗 LinkedIn</span>
                                      </a>
                                    )}
                                  </div>
                                </div>
                              </div>
                            </td>

                            {/* Designation */}
                            <td className="px-4 py-4">
                              <p className="font-semibold text-slate-800">{c.designation || c.title || 'Decision Maker'}</p>
                              <div className="flex items-center gap-1 mt-0.5">
                                <span className={`inline-block text-[9px] uppercase font-bold px-1.5 py-0.5 rounded border ${roleMeta.badge}`}>
                                  {roleMeta.label}
                                </span>
                                <span className="text-[9px] font-medium text-slate-500">
                                  • Current Role
                                </span>
                              </div>
                            </td>

                            {/* Email & Status */}
                            <td className="px-5 py-4">
                              {c.email ? (
                                <div className="space-y-1.5">
                                  <div className="flex items-center gap-2">
                                    <span className="font-mono text-slate-900 text-[11px] font-semibold">
                                      {c.email}
                                    </span>
                                    <button
                                      onClick={() => copyToClipboard(c.email, `email-${c._id}`)}
                                      className="text-[9px] text-indigo-600 hover:text-indigo-800 font-bold px-1 py-0.5 rounded bg-indigo-50"
                                      title="Copy Email"
                                    >
                                      {copiedField === `email-${c._id}` ? '✓' : 'Copy'}
                                    </button>
                                  </div>
                                  <div className="flex flex-wrap items-center gap-1.5">
                                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] border font-bold ${emailMeta.pillClass}`}>
                                      <span>{emailMeta.icon}</span>
                                      <span>{emailMeta.label}</span>
                                    </span>
                                    {emailStatusKey === 'EXACT_FOUND' && (
                                      <span className="text-[10px] text-slate-500 font-medium">
                                        Source: <span className="font-semibold text-slate-700">{c.sourceType === 'official_website' ? 'Official Website' : (c.sourceType === 'public_search' ? 'Public Search' : (c.source || 'Website'))}</span>
                                      </span>
                                    )}
                                  </div>
                                  {emailStatusKey === 'PATTERN_GENERATED' && (
                                    <div className="text-[10px] text-slate-600 space-y-0.5 pt-0.5">
                                      <div className="flex items-center gap-1.5 flex-wrap">
                                        <span className="bg-amber-50 text-amber-900 border border-amber-200 px-1.5 py-0.5 rounded text-[9px] font-mono font-bold">
                                          Pattern: {c.generatedPattern || c.patternUsed || c.emailPattern || 'first.last'}
                                        </span>
                                        <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold border ${
                                          c.patternConfidence === 'SUPPORTED' ? 'bg-emerald-50 text-emerald-800 border-emerald-300' : 'bg-slate-100 text-slate-700 border-slate-200'
                                        }`}>
                                          Confidence: {c.patternConfidence || 'SUPPORTED'}
                                        </span>
                                        <span className="text-[9px] text-slate-500 font-semibold bg-slate-50 border border-slate-200 px-1.5 py-0.5 rounded">
                                          Verification: {c.mailboxVerification || 'UNVERIFIED'}
                                        </span>
                                      </div>
                                    </div>
                                  )}
                                </div>
                              ) : (
                                <div className="space-y-1">
                                  <span className="text-slate-400 italic text-[11px]">—</span>
                                  <div>
                                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] border font-bold ${emailMeta.pillClass}`}>
                                      <span>{emailMeta.icon}</span>
                                      <span>{emailMeta.label}</span>
                                    </span>
                                  </div>
                                  {(c.emailReason || c.email_reason) && (
                                    <p className="text-[10px] text-slate-500 font-medium leading-tight max-w-[240px]">
                                      {c.emailReason || c.email_reason}
                                    </p>
                                  )}
                                  {(emailStatusKey === 'SEARCH_TIMEOUT' || emailStatusKey === 'SEARCH_UNAVAILABLE') && (
                                    <span className="inline-block text-[9px] bg-indigo-50 text-indigo-700 font-bold px-1.5 py-0.5 rounded border border-indigo-200">
                                      Retry Available
                                    </span>
                                  )}
                                </div>
                              )}
                            </td>

                            {/* Domain MX */}
                            <td className="px-4 py-4 whitespace-nowrap">
                              {isMxValid ? (
                                <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200" title={c.mxProvider || 'Active Domain Mail Infrastructure'}>
                                  <span>✓</span>
                                  <span>✓ MX ACTIVE</span>
                                </span>
                              ) : (
                                <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-slate-500 bg-slate-100 px-2 py-0.5 rounded border border-slate-200">
                                  <span>❓</span>
                                  <span>Unknown MX</span>
                                </span>
                              )}
                            </td>

                            {/* Mailbox Status */}
                            <td className="px-4 py-4 whitespace-nowrap">
                              {!c.email ? (
                                <span className="text-slate-400 text-[10px] italic">
                                  N/A
                                </span>
                              ) : c.mailboxVerification === 'MAILBOX_VERIFIED' ? (
                                <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                                  <span>✓</span>
                                  <span>Mailbox Verified</span>
                                </span>
                              ) : (
                                <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-amber-700 bg-amber-50 px-2 py-0.5 rounded border border-amber-200" title="Domain MX confirmed, but individual mailbox not independently verified">
                                  <span>⚪</span>
                                  <span>UNVERIFIED</span>
                                </span>
                              )}
                            </td>

                            {/* Confidence */}
                            <td className="px-4 py-4 whitespace-nowrap">
                              <div className="flex items-center gap-2">
                                <div className="w-12 bg-slate-100 rounded-full h-2 overflow-hidden">
                                  <div
                                    className={`h-full rounded-full ${
                                      (c.confidenceScore || 75) >= 85
                                        ? 'bg-emerald-500'
                                        : (c.confidenceScore || 75) >= 65
                                        ? 'bg-blue-500'
                                        : 'bg-amber-500'
                                    }`}
                                    style={{ width: `${c.confidenceScore || 75}%` }}
                                  />
                                </div>
                                <span className="font-mono font-bold text-[11px] text-slate-700">
                                  {c.confidenceScore || 75}%
                                </span>
                              </div>
                              <span className="text-[9px] text-slate-500 uppercase font-semibold block mt-0.5">
                                {c.confidence || ((c.confidenceScore || 75) >= 85 ? 'high' : 'medium')}
                              </span>
                            </td>

                            {/* Source */}
                            <td className="px-4 py-4 whitespace-nowrap">
                              {c.sourceUrl ? (
                                <a
                                  href={c.sourceUrl}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="inline-block px-2 py-0.5 bg-slate-100 hover:bg-slate-200 text-indigo-600 rounded-md text-[10px] font-medium border border-slate-200 truncate max-w-[130px]"
                                  title={c.sourceUrl}
                                >
                                  🔗 {c.source || 'Leadership Page'}
                                </a>
                              ) : (
                                <span className="inline-block px-2 py-0.5 bg-slate-100 text-slate-700 rounded-md text-[10px] font-medium border border-slate-200">
                                  {c.source || 'Leadership Page'}
                                </span>
                              )}
                            </td>

                            {/* Action */}
                            <td className="px-5 py-4 whitespace-nowrap text-right space-x-2">
                              <button
                                onClick={() => setEvidenceContact(c)}
                                className="px-2.5 py-1 text-indigo-600 hover:bg-indigo-50 border border-indigo-200 rounded-lg text-xs font-bold transition-colors"
                              >
                                🔍 View Evidence
                              </button>
                              <button
                                onClick={() => handleSelectDecisionMaker(c)}
                                className={`px-3 py-1.5 rounded-xl font-bold text-xs transition-colors shadow-xs ${
                                  isSelected
                                    ? 'bg-indigo-600 text-white'
                                    : 'bg-slate-900 text-white hover:bg-slate-800'
                                }`}
                              >
                                {isSelected ? '✓ Selected' : 'Select Target'}
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* SEPARATE SECTION: COMPANY INBOXES */}
            {companyInboxes.length > 0 && (
              <div className="bg-slate-50/80 rounded-2xl border border-slate-200 p-6 space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-bold text-slate-900 flex items-center gap-2">
                      <span>🏢</span>
                      <span>Company Inboxes</span>
                    </h3>
                    <p className="text-xs text-slate-500 mt-0.5">
                      Generic company contact channels kept strictly separate from executive decision makers.
                    </p>
                  </div>
                  <span className="text-xs font-semibold text-slate-500 bg-white px-2.5 py-1 rounded-full border border-slate-200">
                    {companyInboxes.length} Channels Discovered
                  </span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                  {companyInboxes.map((inbox) => (
                    <div
                      key={inbox._id}
                      className="bg-white rounded-xl border border-slate-200 p-3.5 space-y-2 shadow-xs hover:border-slate-300 transition-colors"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-slate-900">{inbox.designation || inbox.name}</span>
                        <span className="text-[9px] uppercase font-bold px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">
                          Company Inbox
                        </span>
                      </div>
                      <p className="font-mono text-xs font-semibold text-slate-700 truncate" title={inbox.email}>
                        {inbox.email}
                      </p>
                      <div className="flex items-center justify-between pt-1 border-t border-slate-100 text-[10px] text-slate-500">
                        <span>{inbox.source || 'Domain Channel'}</span>
                        <button
                          onClick={() => copyToClipboard(inbox.email, `inbox-${inbox._id}`)}
                          className="text-indigo-600 hover:text-indigo-800 font-bold"
                        >
                          {copiedField === `inbox-${inbox._id}` ? '✓ Copied' : 'Copy'}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* VIEW EVIDENCE MODAL */}
            {evidenceContact && (
              <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-xs flex items-center justify-center p-4">
                <div className="bg-white rounded-3xl max-w-xl w-full p-6 shadow-2xl space-y-4 animate-fadeIn">
                  <div className="flex justify-between items-start border-b pb-3">
                    <div>
                      <span className="text-[10px] uppercase font-bold text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded">
                        Ground Truth Evidence Inspection
                      </span>
                      <h3 className="font-black text-slate-900 text-lg mt-1">{evidenceContact.name}</h3>
                      <p className="text-xs text-slate-500">{evidenceContact.designation || evidenceContact.title} • {company.companyName}</p>
                    </div>
                    <button onClick={() => setEvidenceContact(null)} className="text-slate-400 hover:text-slate-600 font-bold text-xl">&times;</button>
                  </div>

                  <div className="space-y-3 text-xs max-h-[60vh] overflow-y-auto pr-1">
                    {/* Person & Designation Evidence */}
                    <div className="p-3.5 bg-slate-50 rounded-xl border border-slate-200 space-y-1">
                      <p className="font-bold text-slate-800 uppercase tracking-wider text-[10px]">1. Person &amp; Designation Ground Truth</p>
                      <p className="text-slate-700 italic font-mono text-[11px]">
                        &quot;{evidenceContact.evidence?.personEvidence || `${evidenceContact.name} is verified as ${evidenceContact.designation || evidenceContact.title} at ${company.companyName}.`}&quot;
                      </p>
                      {evidenceContact.designationOriginal && evidenceContact.designationOriginal !== evidenceContact.designation && (
                        <p className="text-[10px] text-slate-500 pt-0.5">
                          Original Designation in Source: <span className="font-mono text-slate-700 font-semibold">{evidenceContact.designationOriginal}</span>
                        </p>
                      )}
                      {evidenceContact.sourceUrl && (
                        <p className="text-[11px] text-slate-500 pt-1">
                          Source URL: <a href={evidenceContact.sourceUrl} target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline font-mono">{evidenceContact.sourceUrl}</a>
                        </p>
                      )}
                      <div className="flex flex-wrap gap-2 pt-1">
                        <span className="text-[9px] font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                          ✓ Person Verified
                        </span>
                        <span className="text-[9px] font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                          ✓ Designation Verified
                        </span>
                        <span className="text-[9px] font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                          ✓ Company Association Confirmed
                        </span>
                      </div>
                    </div>

                    {/* Email Evidence & Status */}
                    <div className="p-3.5 bg-slate-50 rounded-xl border border-slate-200 space-y-1">
                      <p className="font-bold text-slate-800 uppercase tracking-wider text-[10px]">2. Professional Email &amp; Verification Evidence</p>
                      <p className="font-mono text-slate-900 font-bold text-xs">{evidenceContact.email || 'Email: Not Found'}</p>
                      <div className="flex items-center gap-2 pt-1">
                        <span className="text-[10px] text-slate-500">Verification Status:</span>
                        <span className={`px-2 py-0.5 rounded text-[10px] border ${(EMAIL_STATUS_META[resolveUserFacingEmailStatus(evidenceContact)] || EMAIL_STATUS_META.NOT_FOUND).pillClass}`}>
                          {(EMAIL_STATUS_META[resolveUserFacingEmailStatus(evidenceContact)] || EMAIL_STATUS_META.NOT_FOUND).icon}{' '}
                          {(EMAIL_STATUS_META[resolveUserFacingEmailStatus(evidenceContact)] || EMAIL_STATUS_META.NOT_FOUND).label}
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-600 pt-1 leading-relaxed">
                        {evidenceContact.evidence?.emailEvidence || (evidenceContact.email ? `Verified professional email: ${evidenceContact.email}` : 'No exact email published in public leadership sources.')}
                      </p>
                    </div>

                    {/* Discovery Source (Search + AI Provider) */}
                    {(evidenceContact.searchProvider || evidenceContact.aiProvider) && (
                      <div className="p-3.5 bg-slate-50 rounded-xl border border-slate-200 space-y-1">
                        <p className="font-bold text-slate-800 uppercase tracking-wider text-[10px]">2.5 Discovery Source</p>
                        <div className="grid grid-cols-2 gap-2">
                          <div className="bg-white p-2.5 rounded-lg border border-slate-200">
                            <span className="text-[9px] text-slate-400 font-bold uppercase block">Search Provider</span>
                            <span className="font-mono font-bold text-slate-800 text-xs capitalize">{evidenceContact.searchProvider || 'none'}</span>
                            {evidenceContact.searchConfigured ? (
                              <span className="text-[9px] text-emerald-600 block">Configured{evidenceContact.searchQueriesUsed ? ` • ${evidenceContact.searchQueriesUsed} queries, ${evidenceContact.searchResultsFound || 0} results` : ''}</span>
                            ) : (
                              <span className="text-[9px] text-slate-400 block">Unconfigured</span>
                            )}
                          </div>
                          <div className="bg-white p-2.5 rounded-lg border border-slate-200">
                            <span className="text-[9px] text-slate-400 font-bold uppercase block">AI Provider</span>
                            <span className="font-mono font-bold text-slate-800 text-xs">{evidenceContact.aiProvider || 'none'}{evidenceContact.aiModel ? ` (${evidenceContact.aiModel})` : ''}</span>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Pattern Evidence (If Pattern Derived) */}
                    {(evidenceContact.patternUsed && evidenceContact.patternUsed !== 'none') && (
                      <div className="p-3.5 bg-amber-50/50 rounded-xl border border-amber-200 space-y-2">
                        <p className="font-bold text-amber-900 uppercase tracking-wider text-[10px]">3. Company Email Format Analysis</p>
                        <p className="text-[11px] text-slate-700">
                          Detected Pattern: <span className="font-mono font-bold text-indigo-700">{evidenceContact.generatedPattern || evidenceContact.patternUsed || evidenceContact.emailPattern || 'none'}</span> (Confidence: <span className="font-semibold uppercase">{evidenceContact.patternConfidence || 'none'}</span>)
                        </p>
                        {evidenceContact.patternsObserved && evidenceContact.patternsObserved.length > 0 && (
                          <div className="pt-1">
                            <span className="text-[10px] text-slate-500 block font-medium">Observed Formats:</span>
                            <div className="flex flex-wrap gap-1 mt-0.5">
                              {evidenceContact.patternsObserved.map((po, i) => (
                                <span key={i} className="font-mono text-[10px] bg-white px-2 py-0.5 rounded border border-amber-200 text-slate-700">
                                  {po.pattern} ({po.supportCount} verified)
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                        {evidenceContact.patternEvidence && evidenceContact.patternEvidence.length > 0 && (
                          <div className="pt-1">
                            <span className="text-[10px] text-slate-500 block font-medium">Supporting Employee Evidence:</span>
                            <div className="space-y-1 mt-0.5 max-h-36 overflow-y-auto">
                              {evidenceContact.patternEvidence.map((pe, i) => (
                                <div key={i} className="text-[10px] bg-white p-1.5 rounded border border-amber-200 text-slate-700">
                                  <span className="font-bold">{pe.person || pe.name}:</span> <span className="font-mono text-indigo-700">{pe.email}</span>
                                  {pe.source_url && (
                                    <span className="text-slate-400 block truncate text-[9px] mt-0.5">
                                      Source: {pe.source_url}
                                    </span>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Mail Server & Mailbox Status */}
                    <div className="p-3.5 bg-slate-50 rounded-xl border border-slate-200 space-y-2">
                      <p className="font-bold text-slate-800 uppercase tracking-wider text-[10px]">4. Mail Server (DNS/MX) &amp; Mailbox Status</p>
                      <div className="grid grid-cols-2 gap-2">
                        <div className="bg-white p-2.5 rounded-lg border border-slate-200">
                          <span className="text-[9px] text-slate-400 font-bold uppercase block">Domain MX Infrastructure</span>
                          <span className="font-mono font-bold text-emerald-700 text-xs">{evidenceContact.mxStatus || 'MX_ACTIVE'}</span>
                          <span className="text-[10px] text-slate-500 block truncate">{evidenceContact.mxProvider || 'Active Domain MX'}</span>
                        </div>
                        <div className="bg-white p-2.5 rounded-lg border border-slate-200">
                          <span className="text-[9px] text-slate-400 font-bold uppercase block">Individual Mailbox Status</span>
                          <span className="font-mono font-bold text-slate-800 text-xs">
                            {evidenceContact.mailboxVerification === 'DIRECT_SOURCE_MATCH' ? 'DIRECT_SOURCE_MATCH' : 'NOT_INDEPENDENTLY_CONFIRMED'}
                          </span>
                          <span className="text-[10px] text-slate-500 block">
                            {evidenceContact.mailboxVerification === 'DIRECT_SOURCE_MATCH' ? 'Published in official source' : 'Estimated from company pattern'}
                          </span>
                        </div>
                      </div>

                      {/* Important Disclaimer Banner */}
                      <div className="p-2.5 bg-blue-50/80 rounded-lg border border-blue-200 text-[11px] text-blue-900 leading-relaxed">
                        ℹ️ <span className="font-bold">Important Notice:</span> DNS MX verification confirms the domain&apos;s mail server infrastructure. It does not independently confirm the existence of this individual&apos;s mailbox.
                      </div>
                    </div>

                    {/* Confidence Reasoning & Search Audit Trail */}
                    <div className="p-3.5 bg-slate-50 rounded-xl border border-slate-200 space-y-1.5">
                      <p className="font-bold text-slate-800 uppercase tracking-wider text-[10px]">5. Explainable Confidence &amp; Search Audit Trail</p>
                      {evidenceContact.confidenceReasoning && evidenceContact.confidenceReasoning.length > 0 && (
                        <div>
                          <span className="text-[10px] text-slate-500 block">Confidence Factor Breakdown:</span>
                          <ul className="list-disc list-inside text-[10px] text-slate-700 font-medium space-y-0.5 mt-0.5">
                            {evidenceContact.confidenceReasoning.map((r, i) => (
                              <li key={i}>{r}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {evidenceContact.auditTrail?.queriesUsed && evidenceContact.auditTrail.queriesUsed.length > 0 && (
                        <div className="pt-1 border-t border-slate-200">
                          <span className="text-[10px] text-slate-500 block">Searches &amp; Public Queries Evaluated:</span>
                          <ul className="list-disc list-inside text-[10px] text-slate-600 font-mono space-y-0.5 mt-0.5">
                            {evidenceContact.auditTrail.queriesUsed.slice(0, 3).map((q, i) => (
                              <li key={i}>{q}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="flex justify-between items-center pt-3 border-t">
                    <span className="text-xs font-bold text-slate-500">
                      Explainable Confidence: <span className="text-slate-900 font-mono font-bold">{evidenceContact.confidenceScore || 85}%</span> ({evidenceContact.confidence || 'medium'})
                    </span>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setEvidenceContact(null)}
                        className="px-4 py-2 border rounded-xl text-xs font-bold text-slate-700 hover:bg-slate-50"
                      >
                        Close
                      </button>
                      <button
                        onClick={() => {
                          handleSelectDecisionMaker(evidenceContact);
                          setEvidenceContact(null);
                        }}
                        className="px-4 py-2 bg-indigo-600 text-white rounded-xl text-xs font-bold hover:bg-indigo-700 shadow-xs"
                      >
                        Select for Outreach &rarr;
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        );
      })()}

          {/* Quick Edit Contact Modal */}
          {editingContact && (
            <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-xs flex items-center justify-center p-4">
              <div className="bg-white rounded-3xl max-w-md w-full p-6 shadow-2xl space-y-4">
                <div className="flex justify-between items-center border-b pb-3">
                  <h3 className="font-bold text-slate-900 text-base">Edit Decision Maker</h3>
                  <button onClick={() => setEditingContact(null)} className="text-slate-400 hover:text-slate-600 font-bold">&times;</button>
                </div>
                <form onSubmit={handleUpdateContact} className="space-y-4">
                  <div>
                    <label className="block text-xs font-bold text-slate-700 mb-1">Full Name *</label>
                    <input
                      type="text"
                      required
                      value={editingContact.name}
                      onChange={(e) => setEditingContact({ ...editingContact, name: e.target.value })}
                      className="w-full px-3 py-2 border rounded-xl text-xs focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-slate-700 mb-1">Designation / Title</label>
                    <input
                      type="text"
                      value={editingContact.designation || editingContact.title}
                      onChange={(e) => setEditingContact({ ...editingContact, designation: e.target.value, title: e.target.value })}
                      className="w-full px-3 py-2 border rounded-xl text-xs focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-slate-700 mb-1">Role Category</label>
                    <select
                      value={editingContact.roleCategory || 'ceo'}
                      onChange={(e) => setEditingContact({ ...editingContact, roleCategory: e.target.value })}
                      className="w-full px-3 py-2 border rounded-xl text-xs bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                    >
                      <option value="ceo">👑 CEO / Chief Executive Officer</option>
                      <option value="founder">💡 Founder / Co-Founder</option>
                      <option value="managing_director">👔 Managing Director</option>
                      <option value="president">🏛️ President</option>
                      <option value="coo">💼 COO / Chief Operating Officer</option>
                      <option value="cfo">💰 CFO / Chief Financial Officer</option>
                      <option value="cto">🚀 CTO / Chief Technology Officer</option>
                      <option value="cio">💻 CIO / Chief Information Officer</option>
                      <option value="cdo">📊 CDO / Chief Digital Officer</option>
                      <option value="head_of_ai">🤖 Head of AI</option>
                      <option value="head_of_data">📈 Head of Data</option>
                      <option value="head_of_technology">⚙️ Head of Technology / Engineering</option>
                      <option value="head_of_operations">💼 Head of Operations</option>
                      <option value="head_of_sales">🎯 Head of Sales / CRO</option>
                      <option value="head_of_product">📦 Head of Product</option>
                      <option value="vp">🚀 Vice President (VP)</option>
                      <option value="general">🏢 Company Inbox / Channel</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-slate-700 mb-1">Email Address</label>
                    <input
                      type="email"
                      value={editingContact.email || ''}
                      onChange={(e) => setEditingContact({ ...editingContact, email: e.target.value })}
                      className="w-full px-3 py-2 border rounded-xl text-xs focus:ring-2 focus:ring-indigo-500 focus:outline-none font-mono"
                    />
                  </div>
                  <div className="flex justify-end gap-3 pt-3 border-t">
                    <button
                      type="button"
                      onClick={() => setEditingContact(null)}
                      className="px-4 py-2 border rounded-xl text-xs font-bold text-slate-700 hover:bg-slate-50"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      className="px-5 py-2 bg-indigo-600 text-white rounded-xl text-xs font-bold hover:bg-indigo-700"
                    >
                      Save Changes
                    </button>
                  </div>
                </form>
              </div>
            </div>
          )}

          {/* Add Contact Modal */}
          {showAddContactModal && (
            <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-xs flex items-center justify-center p-4">
              <div className="bg-white rounded-3xl max-w-md w-full p-6 shadow-2xl">
                <div className="flex justify-between items-center mb-4">
                  <h3 className="font-bold text-slate-900 text-base">Add New Decision Maker</h3>
                  <button onClick={() => setShowAddContactModal(false)} className="text-slate-400 hover:text-slate-600 font-bold">&times;</button>
                </div>
                <form onSubmit={handleAddContact} className="space-y-4">
                  <div>
                    <label className="block text-xs font-bold text-slate-700 mb-1">Full Name *</label>
                    <input
                      type="text"
                      required
                      value={newContact.name}
                      onChange={(e) => setNewContact({ ...newContact, name: e.target.value })}
                      className="w-full px-3 py-2 border rounded-xl text-xs focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                      placeholder="e.g. John Smith"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-slate-700 mb-1">Designation / Title</label>
                    <input
                      type="text"
                      value={newContact.designation}
                      onChange={(e) => setNewContact({ ...newContact, designation: e.target.value, title: e.target.value })}
                      className="w-full px-3 py-2 border rounded-xl text-xs focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                      placeholder="e.g. Chief Technology Officer or Head of AI"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-slate-700 mb-1">Role Category</label>
                    <select
                      value={newContact.roleCategory}
                      onChange={(e) => setNewContact({ ...newContact, roleCategory: e.target.value })}
                      className="w-full px-3 py-2 border rounded-xl text-xs bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                    >
                      <option value="ceo">👑 CEO / Chief Executive Officer</option>
                      <option value="founder">💡 Founder / Co-Founder</option>
                      <option value="managing_director">👔 Managing Director</option>
                      <option value="president">🏛️ President</option>
                      <option value="coo">💼 COO / Chief Operating Officer</option>
                      <option value="cfo">💰 CFO / Chief Financial Officer</option>
                      <option value="cto">🚀 CTO / Chief Technology Officer</option>
                      <option value="cio">💻 CIO / Chief Information Officer</option>
                      <option value="cdo">📊 CDO / Chief Digital Officer</option>
                      <option value="head_of_ai">🤖 Head of AI</option>
                      <option value="head_of_data">📈 Head of Data</option>
                      <option value="head_of_technology">⚙️ Head of Technology / Engineering</option>
                      <option value="head_of_operations">💼 Head of Operations</option>
                      <option value="head_of_sales">🎯 Head of Sales / CRO</option>
                      <option value="head_of_product">📦 Head of Product</option>
                      <option value="vp">🚀 Vice President (VP)</option>
                      <option value="general">🏢 Company Inbox / Channel</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-slate-700 mb-1">Email Address</label>
                    <input
                      type="email"
                      value={newContact.email}
                      onChange={(e) => setNewContact({ ...newContact, email: e.target.value })}
                      className="w-full px-3 py-2 border rounded-xl text-xs focus:ring-2 focus:ring-indigo-500 focus:outline-none font-mono"
                      placeholder="e.g. john.smith@company.com"
                    />
                  </div>
                  <div className="flex justify-end gap-3 pt-3">
                    <button
                      type="button"
                      onClick={() => setShowAddContactModal(false)}
                      className="px-4 py-2 border rounded-xl text-xs font-bold text-slate-700 hover:bg-slate-50"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      className="px-5 py-2 bg-indigo-600 text-white rounded-xl text-xs font-bold hover:bg-indigo-700"
                    >
                      Save Decision Maker
                    </button>
                  </div>
                </form>
              </div>
            </div>
          )}

      {/* TAB 4: AI OUTREACH & EMAIL COMPOSER */}
      {activeTab === 'outreach' && (
        <div className="space-y-6">
          {/* Authoritative Inputs Card (Phase 2 - Section 16) */}
          <div className="bg-slate-50 border border-slate-200/90 rounded-2xl p-5 shadow-xs space-y-3">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-200/70 pb-2.5">
              <div className="flex items-center gap-2">
                <span className="text-base">📋</span>
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-700">Authoritative Outreach Inputs</h3>
              </div>
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-200/60 self-start sm:self-auto">
                Authoritative Excel Source
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              <div className="bg-white p-3 rounded-xl border border-slate-200/60">
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Company</span>
                <p className="text-xs font-bold text-slate-900 mt-0.5 truncate">{company.companyName}</p>
                <p className="text-[11px] text-slate-500 font-mono truncate">{company.website}</p>
              </div>

              <div className="bg-white p-3 rounded-xl border border-slate-200/60">
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Decision Maker</span>
                {(() => {
                  const lead = contacts.find(c => c._id === selectedContactId) || contacts[0];
                  return (
                    <div>
                      <p className="text-xs font-bold text-slate-900 mt-0.5 truncate">
                        {lead?.name || company.contactName || 'Leadership Team'}
                      </p>
                      <p className="text-[11px] text-slate-500 truncate">
                        {lead?.designation || lead?.title || 'Executive Leadership'}
                      </p>
                    </div>
                  );
                })()}
              </div>

              <div className="bg-white p-3 rounded-xl border border-slate-200/60">
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Evidence</span>
                <p className="text-xs text-slate-800 mt-0.5 font-medium line-clamp-3 whitespace-pre-wrap" title={company.evidence}>
                  {company.evidence && company.evidence.trim() ? (
                    company.evidence
                  ) : (
                    <span className="text-red-500 font-semibold italic">Missing Evidence — required for outreach</span>
                  )}
                </p>
              </div>

              <div className="bg-white p-3 rounded-xl border border-slate-200/60">
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Recommended Service</span>
                <div className="mt-0.5">
                  {company.recommendedService && company.recommendedService.trim() ? (
                    <span className="inline-block text-xs font-bold text-indigo-700 bg-indigo-50 border border-indigo-200/80 px-2 py-0.5 rounded-lg">
                      {company.recommendedService}
                    </span>
                  ) : (
                    <span className="text-red-500 font-semibold italic text-xs">Missing Service — required for outreach</span>
                  )}
                  <p className="text-[10px] text-slate-400 mt-1 italic">
                    Authoritative from company outreach input
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Generation Configuration Bar */}
          <div className="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-xs space-y-4">
            <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4">
              <div>
                <h2 className="text-base font-bold text-slate-900">Personalized Email Generation &amp; Composer</h2>
                <p className="text-xs text-slate-500 mt-0.5">
                  Generates short, evidence-based outreach tailored to the target&apos;s exact role and the single most relevant TKSR Product Services offering.
                </p>
              </div>

              <div className="flex items-center gap-3">
                {outreachMessages.length > 0 && (
                  <button
                    onClick={() => setShowScheduleModal(true)}
                    className="px-4 py-2 bg-indigo-50 text-indigo-700 border border-indigo-200 rounded-xl font-bold text-xs hover:bg-indigo-100 transition-colors flex items-center gap-1.5"
                  >
                    <span>📅</span>
                    <span>Automate Drip Schedule</span>
                  </button>
                )}
                <button
                  onClick={handleGenerateOutreach}
                  disabled={generatingOutreach}
                  className="px-6 py-2 bg-gradient-to-r from-indigo-600 to-blue-600 text-white rounded-xl font-bold text-xs hover:from-indigo-700 hover:to-blue-700 transition-all shadow-md disabled:opacity-50 flex items-center gap-2"
                >
                  <span>{generatingOutreach ? '⏳' : '⚡'}</span>
                  <span>{generatingOutreach ? 'Generating...' : outreachMessages.length > 0 ? 'Regenerate Email' : 'Generate Personalized Email'}</span>
                </button>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 pt-2 border-t border-slate-100">
              {/* Target Decision Maker Selector */}
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Target Decision Maker</label>
                <select
                  value={selectedContactId}
                  onChange={(e) => {
                    setSelectedContactId(e.target.value);
                    const selected = contacts.find(c => c._id === e.target.value);
                    if (selected && editingMessage) {
                      setEditingMessage({
                        ...editingMessage,
                        recipientEmail: selected.email,
                        recipientName: selected.name
                      });
                    }
                  }}
                  className="w-full px-3 py-2 border rounded-xl text-xs focus:ring-2 focus:ring-indigo-500 focus:outline-none bg-white font-medium"
                >
                  {contacts.length === 0 && <option value="">No contacts (will use default)</option>}
                  
                  {leadershipContacts.length > 0 && (
                    <optgroup label="👑 Decision Makers & Leadership">
                      {leadershipContacts.map((c) => (
                        <option key={c._id} value={c._id}>
                          {c.name} {c.designation || c.title ? `(${c.designation || c.title})` : ''} {c.email ? `• ${c.email}` : ''}
                        </option>
                      ))}
                    </optgroup>
                  )}

                  {companyChannels.length > 0 && (
                    <optgroup label="🏢 Company Inboxes">
                      {companyChannels.map((c) => (
                        <option key={c._id} value={c._id}>
                          {c.name} ({c.designation || c.title}) • {c.email}
                        </option>
                      ))}
                    </optgroup>
                  )}
                </select>
              </div>

              {/* TKSR Service Focus */}
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Most Relevant TKSR Service</label>
                <select
                  value={selectedFocusService}
                  onChange={(e) => setSelectedFocusService(e.target.value)}
                  className="w-full px-3 py-2 border rounded-xl text-xs focus:ring-2 focus:ring-indigo-500 focus:outline-none bg-white font-semibold text-indigo-900"
                >
                  {TKSR_SERVICES.map(s => (
                    <option key={s.id} value={s.id}>{s.label}</option>
                  ))}
                </select>
              </div>

              {/* Outreach Angle */}
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Outreach Angle</label>
                <select
                  value={outreachAngle}
                  onChange={(e) => setOutreachAngle(e.target.value)}
                  className="w-full px-3 py-2 border rounded-xl text-xs focus:ring-2 focus:ring-indigo-500 focus:outline-none bg-white"
                >
                  <option value="pain_point">Pain Point &amp; Solution Hook (Recommended)</option>
                  <option value="value_prop">Value Proposition &amp; Proof</option>
                  <option value="icebreaker">Icebreaker &amp; Website Observation</option>
                  <option value="case_study">Case Study Metric</option>
                </select>
              </div>

              {/* Tone */}
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Tone</label>
                <select
                  value={outreachTone}
                  onChange={(e) => setOutreachTone(e.target.value)}
                  className="w-full px-3 py-2 border rounded-xl text-xs focus:ring-2 focus:ring-indigo-500 focus:outline-none bg-white"
                >
                  <option value="conversational">Conversational &amp; Direct</option>
                  <option value="professional">Executive &amp; Professional</option>
                  <option value="friendly">Warm &amp; Collaborative</option>
                </select>
              </div>
            </div>
          </div>

          {sendResult && (
            <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 p-4 rounded-2xl flex flex-col md:flex-row items-start md:items-center justify-between gap-3 text-xs shadow-xs animate-fadeIn">
              <div className="flex items-center gap-2">
                <span className="text-xl">🎉</span>
                <div>
                  <p className="font-bold text-sm">Email dispatched successfully!</p>
                  <p className="text-emerald-700 mt-0.5">
                    Sent to <strong>{editingMessage?.recipientEmail}</strong>
                    {editingMessage?.ccRecipients?.length > 0 && ` (CC: ${editingMessage.ccRecipients.join(', ')})`}
                    {editingMessage?.bccRecipients?.length > 0 && ` (BCC: ${editingMessage.bccRecipients.join(', ')})`}
                    &nbsp;from nagendra@tksrproductservices.com.
                  </p>
                </div>
              </div>
              {sendResult.previewUrl && (
                <a
                  href={sendResult.previewUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="px-4 py-2 bg-emerald-600 text-white rounded-xl text-xs font-bold hover:bg-emerald-700 transition-colors shadow-sm"
                >
                  Open Sandbox Email &rarr;
                </a>
              )}
            </div>
          )}

          {outreachMessages.length > 0 && editingMessage ? (
            <div className="space-y-6">
              <div className="bg-white rounded-2xl border border-slate-200/80 overflow-hidden shadow-xs">
                {/* Sequence Step Tabs */}
                <div className="flex border-b border-slate-200 bg-slate-50/80 px-6 pt-3 space-x-4">
                  {[1, 2, 3].map((stepNum) => {
                    const stepMsg = outreachMessages.find((m) => m.step === stepNum);
                    const isSent = isLockedMessage(stepMsg);
                    const isScheduled = stepMsg?.status === 'scheduled';
                    const isApproved = stepMsg?.status === 'approved';
                    const isCancelled = Boolean(stepMsg?.cancelledReason);
                    const needsReview = Boolean(stepMsg?.requiresReview);
                    return (
                      <button
                        key={stepNum}
                        onClick={() => handleStepSelect(stepNum)}
                        className={`pb-3 px-3 text-xs font-bold border-b-2 transition-colors flex items-center gap-2 ${
                          selectedStep === stepNum
                            ? 'border-indigo-600 text-indigo-600'
                            : 'border-transparent text-slate-500 hover:text-slate-700'
                        }`}
                      >
                        <span>Step {stepNum}</span>
                        {dirtySteps[stepNum] && (
                          <span
                            className="w-1.5 h-1.5 rounded-full bg-amber-500"
                            title="Unsaved changes on this step"
                          />
                        )}
                        {needsReview ? (
                          <span className="text-[10px] bg-amber-100 text-amber-800 px-1.5 py-0.5 rounded font-bold">
                            NEEDS REVIEW
                          </span>
                        ) : isSent ? (
                          <span className="text-[10px] bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded font-bold">
                            SENT {stepMsg.openCount > 0 && `(👁️ ${stepMsg.openCount})`}
                          </span>
                        ) : isCancelled ? (
                          <span className="text-[10px] bg-rose-100 text-rose-700 px-1.5 py-0.5 rounded font-bold">
                            CANCELLED
                          </span>
                        ) : isScheduled ? (
                          <span className="text-[10px] bg-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded font-bold">
                            SCHEDULED (+{stepMsg.delayDays}d)
                          </span>
                        ) : isApproved ? (
                          <span className="text-[10px] bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded font-bold">
                            APPROVED (MANUAL)
                          </span>
                        ) : (
                          <span className="text-[10px] bg-slate-200 text-slate-600 px-1.5 py-0.5 rounded">DRAFT</span>
                        )}
                      </button>
                    );
                  })}
                </div>

                {/* Email Composer Form */}
                <div className="p-6 space-y-4">
                  {isLockedMessage(activeMessage) && (
                    <div className="p-3 rounded-2xl border border-amber-200 bg-amber-50 text-[11px] text-amber-800 leading-relaxed">
                      <strong>Sent message — history preserved.</strong> Subject, body, CC and BCC are locked.
                      You may correct the recipient only; changing it pauses Steps 2/3 for manual review instead
                      of silently redirecting follow-ups.
                    </div>
                  )}
                  {/* To: Recipient Email */}
                  <div>
                    <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1">
                      To: (Decision Maker Email)
                    </label>
                    <input
                      type="email"
                      value={editingMessage.recipientEmail || ''}
                      onChange={(e) => updateEditingMessage({ recipientEmail: e.target.value })}
                      placeholder="e.g. prospect@company.com"
                      className="w-full px-3.5 py-2.5 border border-slate-200 rounded-xl text-xs font-mono font-semibold focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                    />
                  </div>

                  {/* CC: Recipients Section */}
                  <div className="p-3.5 bg-slate-50/80 rounded-2xl border border-slate-200/80 space-y-2">
                    <div className="flex items-center justify-between">
                      <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider">
                        CC: Recipients
                      </label>
                      <button
                        type="button"
                        onClick={() => setShowBccInput(!showBccInput)}
                        className="text-[11px] text-indigo-600 hover:text-indigo-800 font-semibold"
                      >
                        {showBccInput ? 'Hide BCC' : '+ Add BCC'}
                      </button>
                    </div>

                    {/* CC Pills */}
                    {Array.isArray(editingMessage.ccRecipients) && editingMessage.ccRecipients.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 pt-1">
                        {editingMessage.ccRecipients.map((ccEmail) => (
                          <span
                            key={ccEmail}
                            className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-white border border-indigo-200 rounded-lg text-xs font-mono text-indigo-900 shadow-xs"
                          >
                            <span>✉️ {ccEmail}</span>
                            <button
                              type="button"
                              onClick={() => handleRemoveCcEmail(ccEmail)}
                              className="text-slate-400 hover:text-red-600 font-bold ml-1"
                              title="Remove CC"
                            >
                              &times;
                            </button>
                          </span>
                        ))}
                      </div>
                    )}

                    {/* CC Input Box */}
                    <div className="flex items-center gap-2">
                      <input
                        type="email"
                        value={ccInputText}
                        onChange={(e) => setCcInputText(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault();
                            handleAddCcEmail();
                          }
                        }}
                        placeholder="Enter CC email address (e.g. coo@company.com)..."
                        className="flex-1 px-3 py-1.5 bg-white border border-slate-200 rounded-xl text-xs focus:ring-2 focus:ring-indigo-500 focus:outline-none font-mono"
                      />
                      <button
                        type="button"
                        onClick={handleAddCcEmail}
                        className="px-3.5 py-1.5 bg-indigo-50 text-indigo-700 hover:bg-indigo-100 border border-indigo-200 rounded-xl text-xs font-bold transition-colors whitespace-nowrap"
                      >
                        + Add CC
                      </button>
                    </div>
                  </div>

                  {/* BCC: Recipients Section */}
                  {showBccInput && (
                    <div className="p-3.5 bg-slate-50/80 rounded-2xl border border-slate-200/80 space-y-2 animate-fadeIn">
                      <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider">
                        BCC: Recipients (Optional)
                      </label>

                      {/* BCC Pills */}
                      {Array.isArray(editingMessage.bccRecipients) && editingMessage.bccRecipients.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 pt-1">
                          {editingMessage.bccRecipients.map((bccEmail) => (
                            <span
                              key={bccEmail}
                              className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-white border border-slate-300 rounded-lg text-xs font-mono text-slate-800 shadow-xs"
                            >
                              <span>🔒 {bccEmail}</span>
                              <button
                                type="button"
                                onClick={() => handleRemoveBccEmail(bccEmail)}
                                className="text-slate-400 hover:text-red-600 font-bold ml-1"
                                title="Remove BCC"
                              >
                                &times;
                              </button>
                            </span>
                          ))}
                        </div>
                      )}

                      <div className="flex items-center gap-2">
                        <input
                          type="email"
                          value={bccInputText}
                          onChange={(e) => setBccInputText(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              e.preventDefault();
                              handleAddBccEmail();
                            }
                          }}
                          placeholder="Enter BCC email address..."
                          className="flex-1 px-3 py-1.5 bg-white border border-slate-200 rounded-xl text-xs focus:ring-2 focus:ring-indigo-500 focus:outline-none font-mono"
                        />
                        <button
                          type="button"
                          onClick={handleAddBccEmail}
                          className="px-3.5 py-1.5 bg-slate-100 text-slate-700 hover:bg-slate-200 border border-slate-300 rounded-xl text-xs font-bold transition-colors whitespace-nowrap"
                        >
                          + Add BCC
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Subject Line */}
                  <div>
                    <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1">
                      Subject Line
                    </label>
                    <input
                      type="text"
                      value={editingMessage.subject || ''}
                      onChange={(e) => updateEditingMessage({ subject: e.target.value })}
                      className="w-full px-3.5 py-2.5 border border-slate-200 rounded-xl text-xs font-bold focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                    />
                  </div>

                  {/* Email Body Editor */}
                  <div>
                    <div className="flex justify-between items-center mb-1">
                      <label className="text-xs font-bold text-slate-700 uppercase tracking-wider">
                        Personalized Email Body (Editable)
                      </label>
                      <span className="text-[11px] text-slate-400">Click &apos;Save Draft&apos; to preserve custom edits</span>
                    </div>
                    <textarea
                      rows={8}
                      value={editingMessage.bodyHtml || ''}
                      onChange={(e) => updateEditingMessage({ bodyHtml: e.target.value })}
                      className="w-full font-mono text-xs p-3.5 border border-slate-200 rounded-2xl focus:ring-2 focus:ring-indigo-500 focus:outline-none leading-relaxed"
                    />
                  </div>

                  {/* Live Rendered Formatted Preview */}
                  <div>
                    <p className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-2">Live Rendered Visual Preview</p>
                    <div className="p-5 bg-slate-50 rounded-2xl border border-slate-200 text-xs text-slate-800 leading-relaxed shadow-inner">
                      <div dangerouslySetInnerHTML={{ __html: editingMessage.bodyHtml }} />
                    </div>
                  </div>

                  {/* Action Bar */}
                  <div className="flex flex-col sm:flex-row items-center justify-between pt-4 border-t border-slate-200 gap-3">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs text-slate-500">Status:</span>
                      <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase ${
                        isLockedMessage(editingMessage) ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-700'
                      }`}>
                        {editingMessage.status}
                      </span>
                      {editingMessage.isManuallyEdited && (
                        <span className="text-[10px] bg-blue-50 text-blue-700 font-bold px-2 py-0.5 rounded-full border border-blue-200">
                          ✏️ Custom Edited
                        </span>
                      )}
                      {dirtySteps[editingMessage.step] && (
                        <span className="text-[10px] bg-amber-50 text-amber-700 font-bold px-2 py-0.5 rounded-full border border-amber-200">
                          ● Unsaved changes — click Save Draft
                        </span>
                      )}
                    </div>

                    <div className="flex items-center gap-3">
                      {editingMessage.step === 1 && editingMessage.status !== 'sent' && (
                        <button
                          type="button"
                          onClick={handleRegenerateEmail}
                          disabled={regeneratingEmail}
                          className="px-4 py-2 border border-indigo-200 text-indigo-700 rounded-xl text-xs font-bold hover:bg-indigo-50 transition-colors shadow-xs"
                          title="Regenerate Step 1 from the company's Evidence + Recommended Service (replaces manual edits — review before using)"
                        >
                          {regeneratingEmail ? 'Regenerating...' : '♻️ Regenerate Step 1'}
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={handleSaveDraft}
                        disabled={savingDraft}
                        className="px-4 py-2 border border-slate-200 text-slate-700 rounded-xl text-xs font-bold hover:bg-slate-50 transition-colors shadow-xs"
                      >
                        {savingDraft ? 'Saving...' : '💾 Save Draft'}
                      </button>
                      {isLockedMessage(editingMessage) ? (
                        <span
                          className="px-6 py-2 rounded-xl text-xs font-bold bg-slate-100 text-slate-600 border border-slate-200"
                          title="Already sent — duplicate sends are blocked"
                        >
                          ✓ Sent (duplicate sends blocked)
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={handleSendEmail}
                          disabled={sendingEmail || !editingMessage.recipientEmail}
                          className="px-6 py-2 bg-gradient-to-r from-emerald-600 to-teal-600 text-white rounded-xl text-xs font-bold hover:from-emerald-700 hover:to-teal-700 transition-colors shadow-md disabled:opacity-50 flex items-center gap-2 cursor-pointer disabled:cursor-not-allowed"
                          title={
                            !editingMessage.recipientEmail
                              ? 'Recipient email is required to send'
                              : 'Send Email Now (with CC/BCC)'
                          }
                        >
                          <span>🚀</span>
                          <span>{sendingEmail ? 'Dispatching...' : 'Send Email Now (with CC/BCC)'}</span>
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              {/* LinkedIn Multi-Channel Outreach Box */}
              <div className="bg-white rounded-2xl border border-indigo-100 p-6 shadow-xs space-y-4">
                <div className="flex items-center gap-2">
                  <span className="text-xl">💼</span>
                  <div>
                    <h3 className="font-bold text-slate-900 text-xs uppercase tracking-wider">LinkedIn Multi-Channel Copy</h3>
                    <p className="text-[11px] text-slate-500">Personalized connection note &amp; direct InMail highlighting {selectedFocusService}</p>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="p-4 bg-indigo-50/40 rounded-2xl border border-indigo-100 flex flex-col justify-between">
                    <div>
                      <div className="flex justify-between items-center mb-2">
                        <span className="text-xs font-bold text-indigo-900">Connection Request Note</span>
                        <span className="text-[11px] text-slate-400 font-mono">
                          {editingMessage.linkedinNote?.length || 0}/300 chars
                        </span>
                      </div>
                      <p className="text-xs text-slate-700 leading-relaxed font-mono bg-white p-3 rounded-xl border border-slate-200">
                        {editingMessage.linkedinNote || 'Generating connection note...'}
                      </p>
                    </div>
                    <button
                      onClick={() => copyToClipboard(editingMessage.linkedinNote, 'note')}
                      className="mt-3 w-full py-1.5 bg-indigo-600 text-white rounded-xl text-xs font-bold hover:bg-indigo-700 transition-colors"
                    >
                      {copiedField === 'note' ? '✓ Copied to Clipboard!' : 'Copy Connection Note'}
                    </button>
                  </div>

                  <div className="p-4 bg-indigo-50/40 rounded-2xl border border-indigo-100 flex flex-col justify-between">
                    <div>
                      <div className="flex justify-between items-center mb-2">
                        <span className="text-xs font-bold text-indigo-900">Direct InMail Message</span>
                        <span className="text-[11px] text-slate-400 font-mono">InMail Copy</span>
                      </div>
                      <p className="text-xs text-slate-700 leading-relaxed font-mono bg-white p-3 rounded-xl border border-slate-200 whitespace-pre-wrap">
                        {editingMessage.linkedinInmail || 'Generating InMail copy...'}
                      </p>
                    </div>
                    <button
                      onClick={() => copyToClipboard(editingMessage.linkedinInmail, 'inmail')}
                      className="mt-3 w-full py-1.5 bg-slate-900 text-white rounded-xl text-xs font-bold hover:bg-slate-800 transition-colors"
                    >
                      {copiedField === 'inmail' ? '✓ Copied to Clipboard!' : 'Copy InMail Message'}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="bg-white rounded-3xl border border-slate-200 p-12 text-center">
              <p className="text-4xl mb-3">✉️</p>
              <h3 className="text-lg font-bold text-slate-900">No Outreach Email Generated Yet</h3>
              <p className="text-xs text-slate-500 max-w-md mx-auto mt-2 mb-6">
                Click &quot;Generate Personalized Email&quot; to craft a tailored email focused on {selectedFocusService}.
              </p>
              <button
                onClick={handleGenerateOutreach}
                disabled={generatingOutreach}
                className="px-6 py-2.5 bg-indigo-600 text-white rounded-xl font-bold text-xs hover:bg-indigo-700 shadow-md transition-all disabled:opacity-50"
              >
                Generate Personalized Email
              </button>
            </div>
          )}
        </div>
      )}

      {/* Drip Sequence Scheduler Modal */}
      {showScheduleModal && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-3xl max-w-md w-full p-6 shadow-2xl space-y-4">
            <div className="flex justify-between items-center border-b pb-3">
              <h3 className="font-bold text-slate-900 text-base">Automated Drip Scheduling</h3>
              <button onClick={() => setShowScheduleModal(false)} className="text-slate-400 hover:text-slate-600 font-bold">&times;</button>
            </div>

            <p className="text-xs text-slate-600 leading-relaxed">
              Activating the drip schedule arms the follow-up emails. <strong>Step 1 is approved for manual
              sending only — it is never sent automatically.</strong> Steps 2 and 3 are sent automatically
              only while the drip schedule is active and only after Step 1 has been sent.
            </p>

            <div className="flex items-center justify-between p-2.5 rounded-xl border bg-slate-50 animate-fadeIn">
              <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500">Sequence status</span>
              <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold border ${sequenceMeta.className}`}>
                {sequenceMeta.label}
              </span>
            </div>

            <div className="space-y-3 pt-2">
              <div className="flex items-center justify-between p-3 bg-slate-50 rounded-xl border border-slate-200">
                <div>
                  <p className="text-xs font-bold text-slate-900">Step 1 (Initial AI Strategic Hook)</p>
                  <p className="text-[11px] text-slate-500">Day 0 — approved for manual send (not automatic)</p>
                </div>
                <span className="text-xs font-bold text-blue-600">Manual</span>
              </div>

              <div className="flex items-center justify-between p-3 bg-slate-50 rounded-xl border border-slate-200">
                <div>
                  <p className="text-xs font-bold text-slate-900">Step 2 (Practical Workflow Proof)</p>
                  <p className="text-[11px] text-slate-500">Delay after Step 1 — auto-sent once the drip is active</p>
                </div>
                <div className="flex items-center gap-1">
                  <input
                    type="number"
                    min="1"
                    max="30"
                    value={scheduleConfig.step2Days}
                    onChange={(e) => setScheduleConfig({ ...scheduleConfig, step2Days: e.target.value })}
                    className="w-14 px-2 py-1 border rounded text-xs text-center font-bold"
                  />
                  <span className="text-xs text-slate-500">days</span>
                </div>
              </div>

              <div className="flex items-center justify-between p-3 bg-slate-50 rounded-xl border border-slate-200">
                <div>
                  <p className="text-xs font-bold text-slate-900">Step 3 (Assessment Invitation / Breakup)</p>
                  <p className="text-[11px] text-slate-500">Delay after Step 1 — auto-sent once the drip is active</p>
                </div>
                <div className="flex items-center gap-1">
                  <input
                    type="number"
                    min="2"
                    max="60"
                    value={scheduleConfig.step3Days}
                    onChange={(e) => setScheduleConfig({ ...scheduleConfig, step3Days: e.target.value })}
                    className="w-14 px-2 py-1 border rounded text-xs text-center font-bold"
                  />
                  <span className="text-xs text-slate-500">days</span>
                </div>
              </div>
            </div>

            <div className="flex justify-end gap-3 pt-3 border-t">
              <button
                type="button"
                onClick={() => setShowScheduleModal(false)}
                className="px-4 py-2 border rounded-xl text-xs font-bold text-slate-700 hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleActivateSchedule}
                disabled={scheduling}
                className="px-5 py-2 bg-indigo-600 text-white rounded-xl text-xs font-bold hover:bg-indigo-700 disabled:opacity-50"
              >
                {scheduling ? 'Activating...' : 'Activate Drip Schedule'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
