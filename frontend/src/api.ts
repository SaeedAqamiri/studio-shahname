const J = { "Content-Type": "application/json" };

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) {
    const text = await r.text();
    throw new Error(text || `${r.status} ${r.statusText}`);
  }
  return r.json() as Promise<T>;
}

export const api = {
  health: () => req<any>("/api/health"),
  projects: () => req<{ data: any[] }>("/api/projects"),
  project: (id: string) => req<any>(`/api/projects/${id}`),
  createProject: (body: { name: string; description?: string; style_bible?: any }) =>
    req<any>("/api/projects", { method: "POST", headers: J, body: JSON.stringify(body) }),
  patchProject: (id: string, body: any) =>
    req<any>(`/api/projects/${id}`, { method: "PATCH", headers: J, body: JSON.stringify(body) }),
  pacingProfiles: () => req<{ data: any[] }>("/api/pacing-profiles"),
  characters: (projectId: string) => req<{ data: any[] }>(`/api/projects/${projectId}/characters`),
  createCharacter: (projectId: string, body: any) =>
    req<any>(`/api/projects/${projectId}/characters`, { method: "POST", headers: J, body: JSON.stringify(body) }),
  character: (id: string) => req<any>(`/api/characters/${id}`),
  patchCharacter: (id: string, body: any) =>
    req<any>(`/api/characters/${id}`, { method: "PATCH", headers: J, body: JSON.stringify(body) }),
  deleteCharacter: (id: string) => req<any>(`/api/characters/${id}`, { method: "DELETE" }),
  generate: (id: string, body: any) =>
    req<any>(`/api/characters/${id}/generate`, { method: "POST", headers: J, body: JSON.stringify(body) }),
  canonical: (id: string, imageId: string) =>
    req<any>(`/api/characters/${id}/canonical`, { method: "POST", headers: J, body: JSON.stringify({ image_id: imageId }) }),
  addVariant: (id: string, body: any) =>
    req<any>(`/api/characters/${id}/variants`, { method: "POST", headers: J, body: JSON.stringify(body) }),
  deleteVariant: (id: string, vid: string) =>
    req<any>(`/api/characters/${id}/variants/${vid}`, { method: "DELETE" }),
  voices: () => req<{ data: Record<string, any> }>("/api/voices"),
  setVoice: (id: string, body: any) =>
    req<any>(`/api/characters/${id}/voice`, { method: "PUT", headers: J, body: JSON.stringify(body) }),
  ttsPreview: (body: any) =>
    req<any>("/api/tts/preview", { method: "POST", headers: J, body: JSON.stringify(body) }),
  settings: () => req<any>("/api/settings"),
  saveSettings: (body: any) => req<any>("/api/settings", { method: "PUT", headers: J, body: JSON.stringify(body) }),
  testSettings: (body: any) => req<any>("/api/settings/test", { method: "POST", headers: J, body: JSON.stringify(body) }),
  scripts: (projectId: string) => req<{ data: any[] }>(`/api/projects/${projectId}/scripts`),
  createScript: (projectId: string, body: any) =>
    req<any>(`/api/projects/${projectId}/scripts`, { method: "POST", headers: J, body: JSON.stringify(body) }),
  getScript: (id: string) => req<any>(`/api/scripts/${id}`),
  patchScript: (id: string, body: any) =>
    req<any>(`/api/scripts/${id}`, { method: "PATCH", headers: J, body: JSON.stringify(body) }),
  generateScript: (id: string, body: any) =>
    req<any>(`/api/scripts/${id}/generate`, { method: "POST", headers: J, body: JSON.stringify(body) }),
  patchScene: (id: string, body: any) =>
    req<any>(`/api/scenes/${id}`, { method: "PATCH", headers: J, body: JSON.stringify(body) }),
  addScene: (scriptId: string, body: any) =>
    req<any>(`/api/scripts/${scriptId}/scenes`, { method: "POST", headers: J, body: JSON.stringify(body) }),
  deleteScene: (id: string) => req<any>(`/api/scenes/${id}`, { method: "DELETE" }),
  scene: (id: string) => req<any>(`/api/scenes/${id}`),
  addCast: (sceneId: string, body: any) =>
    req<any>(`/api/scenes/${sceneId}/cast`, { method: "POST", headers: J, body: JSON.stringify(body) }),
  removeCast: (sceneId: string, castId: string) =>
    req<any>(`/api/scenes/${sceneId}/cast/${castId}`, { method: "DELETE" }),
  compileScene: (id: string) => req<any>(`/api/scenes/${id}/compile`, { method: "POST", headers: J, body: "{}" }),
  lookFrame: (id: string, body: any) =>
    req<any>(`/api/scenes/${id}/look-frame`, { method: "POST", headers: J, body: JSON.stringify(body) }),
  upsertShot: (sceneId: string, body: any) =>
    req<any>(`/api/scenes/${sceneId}/shots`, { method: "POST", headers: J, body: JSON.stringify(body) }),
  startRender: (shotId: string, body: any) =>
    req<any>(`/api/shots/${shotId}/render`, { method: "POST", headers: J, body: JSON.stringify(body) }),
  render: (id: string) => req<any>(`/api/renders/${id}`),
  renders: () => req<{ data: any[] }>("/api/renders"),
  cancelRender: (id: string) => req<any>(`/api/renders/${id}/cancel`, { method: "POST" }),
  prevFrame: (sceneId: string) => req<any>(`/api/scenes/${sceneId}/prev-frame`, { method: "POST", headers: J, body: "{}" }),
  finalCut: (projectId: string, body: any) =>
    req<any>(`/api/projects/${projectId}/edit`, { method: "POST", headers: J, body: JSON.stringify(body) }),
  exportAV: (projectId: string, body: any) =>
    req<any>(`/api/projects/${projectId}/export`, { method: "POST", headers: J, body: JSON.stringify(body) }),
  dubScene: (sceneId: string) => req<any>(`/api/scenes/${sceneId}/dub`, { method: "POST", headers: J, body: "{}" }),
  subtitles: (scriptId: string) => req<any>(`/api/scripts/${scriptId}/subtitles`),
  uploadCharacterImage: (id: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<any>(`/api/characters/${id}/images/upload`, { method: "POST", body: fd });
  },
  editCharacter: (id: string, body: any) =>
    req<any>(`/api/characters/${id}/edit`, { method: "POST", headers: J, body: JSON.stringify(body) }),
  cloneVoice: (id: string, file: File, transcript: string) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("transcript", transcript);
    return req<any>(`/api/characters/${id}/voice/clone`, { method: "POST", body: fd });
  },
  uploadVoiceRef: (id: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<any>(`/api/characters/${id}/voice/reference`, { method: "POST", body: fd });
  },
};
