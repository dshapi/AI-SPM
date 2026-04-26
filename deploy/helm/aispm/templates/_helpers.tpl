{{/* deploy/helm/aispm/templates/_helpers.tpl */}}

{{/*
Render a full image reference.
Usage: {{ include "aispm.image" .Values.images.api }}
To use a registry, set repository to "registry.example.com/aispm-api" in values.
Note: $ is the passed arg inside named templates — root context not available here.
*/}}
{{- define "aispm.image" -}}
{{- .repository }}:{{ .tag -}}
{{- end -}}

{{/*
Standard labels applied to every resource.
*/}}
{{- define "aispm.labels" -}}
app.kubernetes.io/managed-by: Helm
app.kubernetes.io/part-of: aispm
{{- end -}}

{{/*
Selector labels for a given component.
Usage: {{ include "aispm.selectorLabels" "spm-api" }}
*/}}
{{- define "aispm.selectorLabels" -}}
app.kubernetes.io/name: {{ . }}
app.kubernetes.io/part-of: aispm
{{- end -}}
