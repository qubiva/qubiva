{{/*
Expand the name of the chart.
*/}}
{{- define "qubiva.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "qubiva.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Common labels applied to all resources.
*/}}
{{- define "qubiva.labels" -}}
app.kubernetes.io/name: {{ include "qubiva.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Values.image.tag | default .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Selector labels for the main app.
*/}}
{{- define "qubiva.selectorLabels" -}}
app.kubernetes.io/name: {{ include "qubiva.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
App image with tag.
*/}}
{{- define "qubiva.image" -}}
{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}
{{- end }}

{{/*
IaC runner image with tag.
*/}}
{{- define "qubiva.iacRunnerImage" -}}
{{ .Values.runners.iac.image }}:{{ .Values.runners.iac.tag | default .Chart.AppVersion }}
{{- end }}

{{/*
Discovery runner image with tag.
*/}}
{{- define "qubiva.discoveryRunnerImage" -}}
{{ .Values.runners.discovery.image }}:{{ .Values.runners.discovery.tag | default .Chart.AppVersion }}
{{- end }}

{{/*
Secret name — use existing or generate.
*/}}
{{- define "qubiva.secretName" -}}
{{- if .Values.existingSecret }}
{{- .Values.existingSecret }}
{{- else }}
{{- include "qubiva.fullname" . }}-secrets
{{- end }}
{{- end }}
