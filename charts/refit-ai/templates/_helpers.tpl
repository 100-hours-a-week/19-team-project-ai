{{/*
Expand the name of the chart.
*/}}
{{- define "refit-ai.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "refit-ai.fullname" -}}
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
Create chart label.
*/}}
{{- define "refit-ai.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels.
*/}}
{{- define "refit-ai.labels" -}}
helm.sh/chart: {{ include "refit-ai.chart" . }}
{{ include "refit-ai.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels.
*/}}
{{- define "refit-ai.selectorLabels" -}}
app.kubernetes.io/name: {{ include "refit-ai.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
ServiceAccount name.
*/}}
{{- define "refit-ai.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "refit-ai.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
App Secret name — 사전 생성된 Secret 또는 인라인 Secret.
사전 생성된 Secret(appSecretName)이 있으면 그것을 우선 사용.
*/}}
{{- define "refit-ai.appSecretName" -}}
{{- if .Values.appSecretName }}
{{- .Values.appSecretName }}
{{- else }}
{{- include "refit-ai.fullname" . }}-env
{{- end }}
{{- end }}
