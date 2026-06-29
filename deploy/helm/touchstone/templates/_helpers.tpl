{{/*
Common template helpers for the Touchstone chart.
*/}}

{{- define "touchstone.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "touchstone.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "touchstone.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Labels applied to every object. */}}
{{- define "touchstone.labels" -}}
helm.sh/chart: {{ include "touchstone.chart" . }}
app.kubernetes.io/part-of: touchstone
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end -}}

{{/* Per-service labels. Call with (dict "root" $ "name" $svcName). */}}
{{- define "touchstone.serviceLabels" -}}
{{ include "touchstone.labels" .root }}
app.kubernetes.io/name: {{ include "touchstone.name" .root }}
app.kubernetes.io/component: {{ .name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
{{- end -}}

{{/* Per-service selector labels (stable; no version churn). */}}
{{- define "touchstone.selectorLabels" -}}
app.kubernetes.io/name: {{ include "touchstone.name" .root }}
app.kubernetes.io/component: {{ .name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
{{- end -}}

{{- define "touchstone.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "touchstone.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/* Fully-qualified image reference for a service. */}}
{{- define "touchstone.image" -}}
{{- $root := .root -}}{{- $svc := .svc -}}
{{- $registry := $root.Values.image.registry -}}
{{- $repo := $svc.image.repository -}}
{{- $tag := $svc.image.tag | default $root.Values.image.tag | default $root.Chart.AppVersion -}}
{{- if $registry -}}
{{- printf "%s/%s:%s" $registry $repo $tag -}}
{{- else -}}
{{- printf "%s:%s" $repo $tag -}}
{{- end -}}
{{- end -}}
