<template>
  <div class="settings-view single-page-layout animate-fade-in">
    <!-- 1. 超紧凑型 Header Banner -->
    <div class="settings-header-compact">
      <div class="header-left-info">
        <div class="header-eyebrow">
          <el-icon><Setting /></el-icon>
          <span>SYSTEM SETTINGS & MODEL CONFIGURATION</span>
        </div>
        <div class="header-title-row">
          <h1 class="header-title text-gradient">AI 大模型与系统偏好配置</h1>
          <span class="header-subtitle-inline">接入多 LLM 端点 (OpenAI / Anthropic / Local LLM) 并管理教学生成偏好</span>
        </div>
      </div>

      <div class="header-actions">
        <el-button size="small" plain class="btn-refresh" @click="loadSettings">
          <el-icon class="mr-1"><Refresh /></el-icon> 刷新
        </el-button>
        <el-button type="primary" size="small" class="btn-create shadow-glow" @click="handleOpenCreateDialog()">
          <el-icon class="mr-1"><Plus /></el-icon> 新建模型配置
        </el-button>
      </div>
    </div>

    <!-- 加载与 Error 状态 -->
    <div v-if="loading" class="loading-wrapper">
      <el-skeleton :rows="4" animated />
    </div>

    <div v-else-if="fetchError" class="error-container">
      <el-icon class="error-icon"><WarningFilled /></el-icon>
      <h3 class="error-title">获取系统设置失败</h3>
      <p class="error-desc">{{ fetchError }}</p>
      <el-button type="primary" plain size="small" @click="loadSettings">
        <el-icon class="mr-1"><Refresh /></el-icon> 重新加载
      </el-button>
    </div>

    <template v-else>
      <!-- 2. 4 维顶部指标概览栏 (双层上下布局，杜绝横向挤压截断) -->
      <div class="metrics-bar">
        <!-- 1. 当前激活模型 -->
        <div class="metric-chip border-indigo">
          <div class="chip-top-row">
            <div class="chip-label-wrap">
              <div class="metric-icon bg-indigo"><el-icon><Cpu /></el-icon></div>
              <span class="chip-label">当前激活模型</span>
            </div>
            <div class="status-badge-wrap">
              <span class="status-dot" :class="{ green: activeConfig }"></span>
              <span class="status-txt">{{ activeConfig ? getProviderLabel(activeConfig.provider) : '等待配置' }}</span>
            </div>
          </div>
          <div class="chip-title-val" :title="activeConfig?.name || activeConfig?.model_name || '未激活'">
            {{ activeConfig ? (activeConfig.name || activeConfig.model_name) : '未接入配置' }}
          </div>
        </div>

        <!-- 2. 已接入配置总数 -->
        <div class="metric-chip border-blue">
          <div class="chip-top-row">
            <div class="chip-label-wrap">
              <div class="metric-icon bg-blue"><el-icon><Platform /></el-icon></div>
              <span class="chip-label">配置端点</span>
            </div>
            <span class="chip-tag tag-blue">OpenAI {{ providerStats.openai }} · Anthropic {{ providerStats.anthropic }}</span>
          </div>
          <div class="chip-title-val">
            {{ modelConfigs.length }} <span class="chip-unit">个服务接入</span>
          </div>
        </div>

        <!-- 3. API 密钥安全防线 -->
        <div class="metric-chip border-emerald">
          <div class="chip-top-row">
            <div class="chip-label-wrap">
              <div class="metric-icon bg-emerald"><el-icon><Key /></el-icon></div>
              <span class="chip-label">密钥防线</span>
            </div>
            <span class="chip-tag tag-emerald">加密隔离</span>
          </div>
          <div class="chip-title-val text-emerald">
            Fernet AES-256
          </div>
        </div>

        <!-- 4. 架构推演引擎 -->
        <div class="metric-chip border-violet">
          <div class="chip-top-row">
            <div class="chip-label-wrap">
              <div class="metric-icon bg-violet"><el-icon><Lightning /></el-icon></div>
              <span class="chip-label">推演引擎</span>
            </div>
            <span class="chip-tag tag-purple">流式 Agent</span>
          </div>
          <div class="chip-title-val text-violet">
            SSE Stream Engine
          </div>
        </div>
      </div>

      <!-- 3. 玻璃态分段 Tabs 控制器 (Segmented Navigation Bar) -->
      <div class="tab-control-bar">
        <div class="segmented-tabs">
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'models' }"
            @click="activeTab = 'models'"
          >
            <el-icon><Cpu /></el-icon>
            <span>模型配置管理</span>
            <span class="tab-badge">{{ modelConfigs.length }}</span>
          </button>

          <button
            class="tab-btn"
            :class="{ active: activeTab === 'preferences' }"
            @click="activeTab = 'preferences'"
          >
            <el-icon><Select /></el-icon>
            <span>默认生成偏好</span>
          </button>

          <button
            class="tab-btn"
            :class="{ active: activeTab === 'protocols' }"
            @click="activeTab = 'protocols'"
          >
            <el-icon><Monitor /></el-icon>
            <span>协议支持与引擎状态</span>
          </button>
        </div>

        <!-- Tab 右侧快捷预设工具条 -->
        <div v-if="activeTab === 'models'" class="quick-presets-strip">
          <span class="strip-label">快捷预设填入:</span>
          <button class="mini-preset-btn chip-deepseek" @click="handleOpenCreateDialog('deepseek')">
            <span class="btn-dot bg-blue-500"></span> DeepSeek V3
          </button>
          <button class="mini-preset-btn chip-openai" @click="handleOpenCreateDialog('openai')">
            <span class="btn-dot bg-emerald-500"></span> GPT-4o
          </button>
          <button class="mini-preset-btn chip-ollama" @click="handleOpenCreateDialog('ollama')">
            <span class="btn-dot bg-amber-500"></span> Ollama 本地
          </button>
          <button class="mini-preset-btn chip-claude" @click="handleOpenCreateDialog('claude')">
            <span class="btn-dot bg-purple-500"></span> Claude 3.5
          </button>
        </div>
      </div>

      <!-- 4. Tab 视图内容主体 -->
      <div class="tab-content-container">
        <!-- TAB 1: 模型配置管理 -->
        <div v-if="activeTab === 'models'" class="tab-pane animate-fade-in">
          <!-- 空状态 -->
          <div v-if="modelConfigs.length === 0" class="empty-onboarding-card">
            <div class="empty-header">
              <div class="empty-icon-glow">
                <el-icon><Cpu /></el-icon>
              </div>
              <div class="empty-meta">
                <h3 class="empty-title">暂未配置 AI 大模型端点</h3>
                <p class="empty-sub">点击下方任一预设快捷接入，或点击右上角按钮手动添加自定义配置：</p>
              </div>
            </div>

            <div class="preset-cards-grid">
              <div class="preset-card card-deepseek" @click="handleOpenCreateDialog('deepseek')">
                <div class="preset-card-top">
                  <span class="preset-badge badge-blue">DeepSeek</span>
                  <span class="action-hint">一键接入 &rarr;</span>
                </div>
                <div class="preset-name">DeepSeek V3 官方 API</div>
                <div class="preset-url">https://api.deepseek.com/v1</div>
              </div>

              <div class="preset-card card-openai" @click="handleOpenCreateDialog('openai')">
                <div class="preset-card-top">
                  <span class="preset-badge badge-emerald">OpenAI</span>
                  <span class="action-hint">一键接入 &rarr;</span>
                </div>
                <div class="preset-name">OpenAI GPT-4o 端点</div>
                <div class="preset-url">https://api.openai.com/v1</div>
              </div>

              <div class="preset-card card-ollama" @click="handleOpenCreateDialog('ollama')">
                <div class="preset-card-top">
                  <span class="preset-badge badge-amber">Ollama</span>
                  <span class="action-hint">一键接入 &rarr;</span>
                </div>
                <div class="preset-name">Ollama 本地 11434 端点</div>
                <div class="preset-url">http://localhost:11434/v1</div>
              </div>

              <div class="preset-card card-claude" @click="handleOpenCreateDialog('claude')">
                <div class="preset-card-top">
                  <span class="preset-badge badge-purple">Claude</span>
                  <span class="action-hint">一键接入 &rarr;</span>
                </div>
                <div class="preset-name">Claude 3.5 Sonnet 端点</div>
                <div class="preset-url">https://api.anthropic.com</div>
              </div>
            </div>
          </div>

          <!-- 模型卡片列表 -->
          <div v-else class="model-cards-grid">
            <div
              v-for="config in modelConfigs"
              :key="config.id"
              class="config-card"
              :class="{ active: config.is_active }"
            >
              <div>
                <div class="config-card-header">
                  <div class="badge-group">
                    <span class="provider-badge" :class="getProviderBadgeClass(config.provider)">
                      {{ getProviderLabel(config.provider) }}
                    </span>
                    <span v-if="config.is_active" class="active-tag">
                      <span class="pulse-dot"></span> 当前激活
                    </span>
                  </div>

                  <el-dropdown trigger="click" @command="(cmd: string | number | object) => handleCardCommand(String(cmd), config)">
                    <el-button circle plain size="small" class="dropdown-trigger-btn">
                      <el-icon><MoreFilled /></el-icon>
                    </el-button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item command="edit"><el-icon><Edit /></el-icon> 编辑配置</el-dropdown-item>
                        <el-dropdown-item command="test"><el-icon><Connection /></el-icon> 测试连通性</el-dropdown-item>
                        <el-dropdown-item v-if="!config.is_active" command="activate"><el-icon><Check /></el-icon> 设为激活</el-dropdown-item>
                        <el-dropdown-item command="delete" divided class="text-danger"><el-icon><Delete /></el-icon> 删除配置</el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </div>

                <h3 class="config-title" :title="config.name">{{ config.name || config.model_name }}</h3>

                <div class="url-display-box">
                  <el-icon class="url-icon"><Link /></el-icon>
                  <span class="url-text" :title="config.base_url">{{ config.base_url }}</span>
                  <el-tooltip content="复制 Base URL" placement="top">
                    <button class="copy-btn" @click.stop="copyToClipboard(config.base_url)">
                      <el-icon><CopyDocument /></el-icon>
                    </button>
                  </el-tooltip>
                </div>

                <div class="config-details-compact">
                  <div class="detail-item">
                    <span class="lbl">模型:</span>
                    <span class="val font-mono">{{ config.model_name }}</span>
                  </div>
                  <div class="detail-item">
                    <span class="lbl">Key:</span>
                    <span v-if="config.api_key_configured" class="val key-ok"><el-icon><Lock /></el-icon> {{ config.api_key_masked }}</span>
                    <span v-else class="val key-no"><el-icon><Warning /></el-icon> 未配置</span>
                  </div>
                  <div class="detail-item">
                    <span class="lbl">超时:</span>
                    <span class="val">{{ config.timeout_seconds }}s</span>
                  </div>
                  <div class="detail-item">
                    <span class="lbl">上下文:</span>
                    <span class="val">{{ formatContextWindow(config.context_window_tokens) }}</span>
                  </div>
                  <div class="detail-item">
                    <span class="lbl">能力:</span>
                    <span class="val" :class="config.supports_multimodal ? 'text-violet' : ''">
                      {{ config.supports_multimodal ? '多模态' : '纯文本' }}
                    </span>
                  </div>
                </div>
              </div>

              <div class="config-card-footer">
                <el-button
                  size="small"
                  plain
                  class="card-btn"
                  :loading="testingConfigId === config.id"
                  @click="handleTestCard(config)"
                >
                  <el-icon class="mr-1"><Connection /></el-icon> 测试链接
                </el-button>

                <el-button
                  v-if="!config.is_active"
                  type="success"
                  plain
                  size="small"
                  class="card-btn"
                  :loading="activatingConfigId === config.id"
                  @click="handleActivate(config.id)"
                >
                  <el-icon class="mr-1"><Check /></el-icon> 设为激活
                </el-button>

                <el-button
                  v-else
                  type="primary"
                  plain
                  size="small"
                  class="card-btn"
                  @click="handleEditConfig(config)"
                >
                  <el-icon class="mr-1"><Edit /></el-icon> 编辑修改
                </el-button>
              </div>
            </div>
          </div>
        </div>

        <!-- TAB 2: 默认生成偏好 (精致化配对，单屏饱满无错位) -->
        <div v-else-if="activeTab === 'preferences'" class="tab-pane animate-fade-in">
          <div class="preferences-grid">
            <!-- 左侧卡片：偏好设置表单 -->
            <div class="pref-card lf-card">
              <div class="card-head">
                <h3 class="pane-card-title">
                  <span>全局教学生成偏好</span>
                </h3>
                <span class="title-sub">生成微课蓝图时自动应用</span>
              </div>

              <el-form label-position="top" :model="preferenceForm" class="pref-form">
                <el-form-item label="默认输出语言">
                  <el-select v-model="preferenceForm.default_language" class="w-full" size="default">
                    <el-option label="简体中文 (zh-CN)" value="zh-CN" />
                    <el-option label="English (en-US)" value="en-US" />
                  </el-select>
                </el-form-item>

                <el-form-item label="默认适用学段">
                  <el-select v-model="preferenceForm.default_grade_level" placeholder="未设置（生成时指定）" class="w-full" clearable size="default">
                    <el-option label="小学 (Primary)" value="primary" />
                    <el-option label="初中 (Junior High)" value="junior_high" />
                    <el-option label="高中 (Senior High)" value="senior_high" />
                    <el-option label="大学/职业教育 (Higher Ed)" value="higher_ed" />
                  </el-select>
                </el-form-item>

                <el-form-item label="默认 PPT 导出模板">
                  <el-select v-model="preferenceForm.default_ppt_template" class="w-full" size="default">
                    <el-option v-for="item in pptTemplates" :key="item.id" :label="item.name" :value="item.id" />
                  </el-select>
                </el-form-item>

                <div class="form-btn-row">
                  <el-button type="primary" size="default" class="w-full shadow-glow save-pref-btn" :loading="savingPreferences" @click="handleSavePreferences">
                    <el-icon class="mr-1.5"><Select /></el-icon> 保存偏好设置
                  </el-button>
                </div>
              </el-form>

              <!-- 偏好生效概览与蓝图推演规约面板 (填补左侧空白) -->
              <div class="preference-active-summary">
                <div class="summary-title-line">
                  <el-icon><Lightning /></el-icon>
                  <span>偏好生效与蓝图推演规约</span>
                </div>
                <div class="summary-chips-grid">
                  <div class="summary-chip-item">
                    <span class="chip-k">输出语言</span>
                    <span class="chip-v">{{ preferenceForm.default_language === 'zh-CN' ? '简体中文' : 'English' }}</span>
                  </div>
                  <div class="summary-chip-item">
                    <span class="chip-k">适用学段</span>
                    <span class="chip-v">{{ getGradeLabel(preferenceForm.default_grade_level) }}</span>
                  </div>
                  <div class="summary-chip-item">
                    <span class="chip-k">PPT 导出模板</span>
                    <span class="chip-v highlight">{{ getTemplateName(preferenceForm.default_ppt_template) }}</span>
                  </div>
                  <div class="summary-chip-item">
                    <span class="chip-k">画面画幅比例</span>
                    <span class="chip-v">16:9 标准高清</span>
                  </div>
                </div>
                <p class="summary-footer-tip">修改保存后，新建微课项目或 Agent 重新推演蓝图时将自动装配以上偏好。</p>
              </div>
            </div>

            <!-- 右侧卡片：PPT 模板 Preview (动态色彩与科技感幻灯片 Cover 效果) -->
            <div class="pref-card lf-card">
              <div class="card-head">
                <h3 class="pane-card-title">
                  <span>PPT 主题模板排版预览</span>
                </h3>
                <span class="title-sub">点击卡片设为默认模板</span>
              </div>

              <div class="template-vertical-list">
                <div
                  v-for="item in pptTemplates"
                  :key="item.id"
                  class="visual-tpl-card-compact"
                  :class="{ selected: preferenceForm.default_ppt_template === item.id }"
                  @click="preferenceForm.default_ppt_template = item.id"
                >
                  <div 
                    class="slide-thumb-cover" 
                    :style="{ background: `linear-gradient(135deg, ${item.palette?.primary || '#1e40af'} 0%, ${item.palette?.secondary || '#3b82f6'} 100%)` }"
                  >
                    <div class="slide-cover-inner">
                      <div class="cover-top-tag"></div>
                      <div class="cover-title-line"></div>
                      <div class="cover-sub-lines">
                        <span class="sub-line l1"></span>
                        <span class="sub-line l2"></span>
                      </div>
                    </div>
                  </div>

                  <div class="slide-info-wrap">
                    <div class="slide-info-top">
                      <span class="slide-name">{{ item.name }}</span>
                      <span v-if="preferenceForm.default_ppt_template === item.id" class="checked-badge-pill">
                        <el-icon><Check /></el-icon> 当前选中
                      </span>
                    </div>
                    <p class="slide-desc">{{ item.description }}适用于{{ item.recommended_for.join('、') }}。</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- TAB 3: 协议支持与引擎状态 -->
        <div v-else-if="activeTab === 'protocols'" class="tab-pane animate-fade-in">
          <div class="protocols-grid">
            <!-- 左侧 3 协议说明 -->
            <div class="protocol-cards-column">
              <div class="protocol-box">
                <div class="protocol-box-header">
                  <div class="flex items-center gap-2">
                    <span class="protocol-icon bg-blue-50 text-blue-600"><el-icon><Platform /></el-icon></span>
                    <span class="protocol-name">OpenAI 兼容协议</span>
                  </div>
                  <span class="protocol-tag tag-blue font-mono">/v1/chat/completions</span>
                </div>
                <p class="protocol-desc">适配 OpenAI 官方、DeepSeek (V3/R1)、Kimi、Qwen、Ollama (11434)、vLLM 等端点。</p>
                <div class="protocol-footer">支持模型: gpt-4o, deepseek-chat, qwen-max, llama3</div>
              </div>

              <div class="protocol-box">
                <div class="protocol-box-header">
                  <div class="flex items-center gap-2">
                    <span class="protocol-icon bg-amber-50 text-amber-600"><el-icon><Cpu /></el-icon></span>
                    <span class="protocol-name">Anthropic 协议</span>
                  </div>
                  <span class="protocol-tag tag-amber font-mono">/v1/messages</span>
                </div>
                <p class="protocol-desc">适配 Claude 3.5 Sonnet / Haiku 原生 API 端点，支持 System Prompt 拆分与思考 Token 模式。</p>
                <div class="protocol-footer">支持模型: claude-3-5-sonnet, claude-3-5-haiku</div>
              </div>
            </div>

            <!-- 右侧 引擎运行时控制台卡片 -->
            <div class="runtime-status-card glass-dark-card">
              <div class="bg-watermark"><el-icon><Cpu /></el-icon></div>
              <h3 class="runtime-card-title">
                <el-icon class="ic-indigo"><Monitor /></el-icon> 引擎运行时状态
              </h3>
              <div class="runtime-info-list">
                <div class="runtime-info-row">
                  <span class="rt-label">架构协议引擎:</span>
                  <span class="rt-val text-emerald font-mono">SSE + Stream Engine</span>
                </div>
                <div class="runtime-info-row">
                  <span class="rt-label">多 Agent 支持:</span>
                  <span class="rt-val text-indigo font-mono">Intake / Blueprint / Resource</span>
                </div>
                <div class="runtime-info-row">
                  <span class="rt-label">密钥存储方案:</span>
                  <span class="rt-val font-mono">Fernet AES-256 加密隔离</span>
                </div>
                <div class="runtime-info-row no-border">
                  <span class="rt-label">平台版本:</span>
                  <span class="rt-val font-mono text-muted">LessonForge AI v1.2</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- 创建 / 编辑模型配置的对话框 (ElDialog) -->
    <el-dialog
      v-model="dialogVisible"
      width="640px"
      top="5vh"
      destroy-on-close
      class="config-modal-dialog"
    >
      <template #header>
        <div class="modal-custom-header">
          <div class="modal-header-icon bg-indigo">
            <el-icon><Cpu v-if="!editingConfigId" /><Edit v-else /></el-icon>
          </div>
          <div>
            <h3 class="modal-header-title">{{ editingConfigId ? '修改 AI 模型配置' : '添加 AI 模型配置' }}</h3>
            <p class="modal-header-sub">配置端点、模型能力、上下文窗口与请求参数</p>
          </div>
        </div>
      </template>

      <!-- 快捷预设条 -->
      <div v-if="!editingConfigId" class="preset-dialog-bar">
        <span class="preset-bar-title">
          <el-icon class="ic-indigo"><Lightning /></el-icon> 快捷填入:
        </span>
        <div class="preset-bar-btns">
          <button class="preset-chip chip-blue" @click="applyPreset('deepseek')">DeepSeek V3</button>
          <button class="preset-chip chip-emerald" @click="applyPreset('openai')">OpenAI GPT-4o</button>
          <button class="preset-chip chip-amber" @click="applyPreset('ollama')">Ollama 本地</button>
          <button class="preset-chip chip-purple" @click="applyPreset('claude')">Claude 3.5</button>
        </div>
      </div>

      <el-form
        ref="formRef"
        :model="configForm"
        :rules="formRules"
        label-position="top"
        class="dialog-form"
      >
        <el-form-item label="配置别名/名称" prop="name">
          <el-input v-model="configForm.name" placeholder="如：DeepSeek-V3 生产环境 / Claude 3.5 Sonnet" />
        </el-form-item>

        <div class="dialog-form-row">
          <el-form-item label="协议类型 (Provider)" prop="provider" class="form-col">
            <el-select v-model="configForm.provider" class="w-full" @change="handleProviderChange">
              <el-option label="OpenAI 兼容协议" value="openai_compatible" />
              <el-option label="Anthropic 协议" value="anthropic" />
              <el-option label="Mock 模拟服务" value="mock" />
            </el-select>
          </el-form-item>

          <el-form-item label="模型名称 (Model Identifier)" prop="model_name" class="form-col">
            <el-input v-model="configForm.model_name" placeholder="如：gpt-4o, deepseek-chat" />
          </el-form-item>
        </div>

        <el-form-item label="接口 Base URL (API 端点)" prop="base_url">
          <el-input v-model="configForm.base_url" placeholder="如：https://api.openai.com/v1" />
          <div class="url-hint-row">
            <span>基础 URL，结尾请勿添加 `/chat/completions`</span>
            <span v-if="configForm.base_url.includes('/chat/completions')" class="clean-link" @click="cleanBaseUrl">[自动清理]</span>
          </div>
        </el-form-item>

        <el-form-item label="API Key 密钥">
          <el-input v-model="configForm.api_key" type="password" show-password :placeholder="editingConfigId ? '留空则保持当前 Key 不变' : 'sk-...' " />
          <div v-if="editingConfigId && currentEditingMaskedKey" class="key-masked-hint">
            <el-icon><Lock /></el-icon> 当前加密存储: {{ currentEditingMaskedKey }}
          </div>
        </el-form-item>

        <div class="dialog-form-row">
          <el-form-item label="请求超时时间 (秒)" class="form-col">
            <el-input-number v-model="configForm.timeout_seconds" :min="10" :max="600" class="w-full" />
          </el-form-item>

          <el-form-item label="上下文窗口 (tokens)" prop="context_window_tokens" class="form-col">
            <el-input-number v-model="configForm.context_window_tokens" :min="1" :step="1000" class="w-full" />
          </el-form-item>
        </div>

        <div class="dialog-form-row capability-switch-row">
          <el-form-item label="模型能力" class="form-col">
            <el-checkbox-group v-model="configForm.capabilities" class="capability-checks">
              <el-checkbox value="text_generation">文本生成</el-checkbox>
              <el-checkbox value="structured_output">结构化输出</el-checkbox>
              <el-checkbox value="vision_review">视觉复核</el-checkbox>
              <el-checkbox value="image_generation">图片生成</el-checkbox>
              <el-checkbox value="video_generation">视频生成</el-checkbox>
              <el-checkbox value="speech_generation">语音生成</el-checkbox>
              <el-checkbox value="media_composition">媒体合成</el-checkbox>
            </el-checkbox-group>
          </el-form-item>

          <el-form-item label="激活状态" class="form-col">
            <div class="pt-1"><el-switch v-model="configForm.is_active" active-text="设为当前激活" /></div>
          </el-form-item>
        </div>

        <el-form-item v-if="hasSpecializedTransport" label="媒体接口模式">
          <el-select v-model="configForm.api_mode" class="w-full">
            <el-option v-if="hasImageCapability" label="OpenAI Images / Vision" value="openai_images" />
            <el-option v-if="hasImageCapability" label="Google Gemini Image" value="google_gemini_image" />
            <el-option v-if="hasImageCapability" label="Google Gemini Vision" value="google_vision" />
            <el-option v-if="hasImageCapability" label="Anthropic Vision" value="anthropic_vision" />
            <el-option v-if="hasImageCapability" label="自定义图片 HTTP" value="custom_image_http" />
            <el-option v-if="configForm.capabilities.includes('video_generation')" label="自定义异步视频 HTTP" value="custom_video_async_http" />
            <el-option v-if="configForm.capabilities.includes('speech_generation')" label="自定义语音 HTTP" value="custom_speech_http" />
            <el-option v-if="configForm.capabilities.includes('media_composition')" label="本地 FFmpeg" value="local_ffmpeg" />
            <el-option v-if="hasMediaCapability" label="Mock 媒体服务" value="mock_media" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="isCustomMediaTransport" label="自定义接口映射（JSON）">
          <el-input v-model="configForm.adapter_config_json_text" type="textarea" :rows="7" :placeholder="adapterConfigPlaceholder" />
          <div class="url-hint-row">
            仅支持安全字段映射，不执行脚本。视频接口可配置创建、轮询、取消、状态、进度与结果路径；远程媒体 URL 必须为 HTTPS 且不能指向内网。
          </div>
        </el-form-item>
        <div v-if="configForm.capabilities.includes('video_generation')" class="dialog-form-row">
          <el-form-item label="视频并发数" class="form-col">
            <el-input-number v-model="configForm.media_max_concurrency" :min="1" :max="16" class="w-full" />
          </el-form-item>
          <el-form-item label="轮询间隔（秒）" class="form-col">
            <el-input-number v-model="configForm.media_poll_interval_seconds" :min="0.5" :max="60" :step="0.5" class="w-full" />
          </el-form-item>
        </div>
        <div v-if="configForm.capabilities.includes('video_generation')" class="dialog-form-row">
          <el-form-item label="最大视频时长（秒）" class="form-col">
            <el-input-number v-model="configForm.media_max_duration_seconds" :min="1" :max="7200" class="w-full" />
          </el-form-item>
          <el-form-item label="最大媒体文件（MB）" class="form-col">
            <el-input-number v-model="configForm.media_max_file_mb" :min="1" :max="4096" class="w-full" />
          </el-form-item>
        </div>

        <div v-if="testResult" class="test-result-banner" :class="testResult.success ? 'bg-success' : 'bg-danger'">
          <div class="banner-content">
            <el-icon :class="testResult.success ? 'ic-success' : 'ic-danger'"><CircleCheckFilled v-if="testResult.success" /><CircleCloseFilled v-else /></el-icon>
            <span>{{ testResult.message }}</span>
          </div>
        </div>
      </el-form>

      <template #footer>
        <div class="dialog-footer">
          <el-button plain :loading="testingConnection" @click="handleTestInDialog">
            <el-icon class="mr-1"><Connection /></el-icon> 测试连通性
          </el-button>
          <div class="dialog-footer-actions">
            <el-button @click="dialogVisible = false">取消</el-button>
            <el-button type="primary" :loading="submitting" @click="handleSubmitConfig">保存配置</el-button>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue';
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus';
import {
  Setting,
  Plus,
  Refresh,
  MoreFilled,
  Edit,
  Connection,
  Check,
  Delete,
  Warning,
  WarningFilled,
  Lock,
  Link,
  CopyDocument,
  Lightning,
  Key,
  Platform,
  Select,
  Cpu,
  Monitor,
  CircleCheckFilled,
  CircleCloseFilled,
} from '@element-plus/icons-vue';
import { settingsApi } from '../api/settings';
import { pptTemplatesApi } from '../api/pptTemplates';
import type { PPTTemplate } from '../types';
import type { ModelConfigItem, UserPreferencesPayload } from '../types/settings';
import { useModelConfigStore } from '../stores/modelConfigs';

// 页面全局状态
const loading = ref(true);
const fetchError = ref('');
const submitting = ref(false);
const savingPreferences = ref(false);
const testingConfigId = ref<string | null>(null);
const activatingConfigId = ref<string | null>(null);
const testingConnection = ref(false);

const activeTab = ref<'models' | 'preferences' | 'protocols'>('preferences');
const modelConfigStore = useModelConfigStore();
const modelConfigs = ref<ModelConfigItem[]>([]);
const activeConfigId = ref<string | null>(null);
const pptTemplates = ref<PPTTemplate[]>([]);

const preferenceForm = reactive<UserPreferencesPayload>({
  default_language: 'zh-CN',
  default_grade_level: '',
  default_ppt_template: 'lessonforge_deck_academic',
});

// 计算属性
const activeConfig = computed(() => {
  return modelConfigs.value.find(c => c.is_active) || modelConfigs.value[0] || null;
});

const providerStats = computed(() => {
  const stats = { openai: 0, anthropic: 0, mock: 0 };
  for (const item of modelConfigs.value) {
    if (item.provider === 'openai_compatible') stats.openai++;
    else if (item.provider === 'anthropic') stats.anthropic++;
    else if (item.provider === 'mock') stats.mock++;
  }
  return stats;
});

// 对话框表单状态
const dialogVisible = ref(false);
const editingConfigId = ref<string | null>(null);
const currentEditingMaskedKey = ref('');
const formRef = ref<FormInstance>();
const testResult = ref<{ success: boolean; message: string } | null>(null);

const configForm = reactive({
  name: '',
  provider: 'openai_compatible',
  base_url: 'https://api.openai.com/v1',
  model_name: 'gpt-4o',
  api_key: '',
  timeout_seconds: 90,
  context_window_tokens: 1_000_000,
  supports_multimodal: false,
  capabilities: ['text_generation', 'structured_output'] as ModelCapability[],
  api_mode: 'text_chat',
  adapter_config_json_text: '{}',
  media_max_concurrency: 2,
  media_poll_interval_seconds: 2,
  media_max_duration_seconds: 1800,
  media_max_file_mb: 500,
  is_active: true,
});

const formRules: FormRules = {
  provider: [{ required: true, message: '请选择协议类型', trigger: 'change' }],
  model_name: [{ required: true, message: '请输入模型名称', trigger: 'blur' }],
  base_url: [{ required: true, message: '请输入 Base URL', trigger: 'blur' }],
  context_window_tokens: [{ required: true, message: '请输入上下文窗口', trigger: 'change' }],
};

type ModelCapability = ModelConfigItem['capabilities'][number];

const hasImageCapability = computed(() => (
  configForm.capabilities.includes('image_generation')
  || configForm.capabilities.includes('vision_review')
));
const hasMediaCapability = computed(() => (
  configForm.capabilities.includes('video_generation')
  || configForm.capabilities.includes('speech_generation')
  || configForm.capabilities.includes('media_composition')
));
const hasSpecializedTransport = computed(() => hasImageCapability.value || hasMediaCapability.value);
const isCustomMediaTransport = computed(() => [
  'custom_image_http',
  'custom_video_async_http',
  'custom_speech_http',
].includes(configForm.api_mode));
const adapterConfigPlaceholder = computed(() => {
  if (configForm.api_mode === 'custom_video_async_http') {
    return '{"endpoint_path":"/videos/generations","poll_endpoint_path":"/videos/generations/{job_id}","cancel_endpoint_path":"/videos/generations/{job_id}/cancel","job_id_path":"id","status_path":"status","progress_path":"progress","result_url_path":"output.url"}';
  }
  if (configForm.api_mode === 'custom_speech_http') {
    return '{"endpoint_path":"/audio/speech","prompt_field":"input","voice_field":"voice","response_url_path":"audio.url"}';
  }
  return '{"endpoint_path":"/images/generations","prompt_field":"prompt","response_base64_path":"data.0.b64_json"}';
});

function preferredTestCapability(capabilities: ModelCapability[]) {
  if (capabilities.includes('video_generation')) return 'video_generation' as const;
  if (capabilities.includes('speech_generation')) return 'speech_generation' as const;
  if (capabilities.includes('image_generation')) return 'image_generation' as const;
  return 'text_generation' as const;
}

function adapterWithMediaLimits(adapter: Record<string, unknown>) {
  if (!configForm.capabilities.includes('video_generation')) return adapter;
  return {
    ...adapter,
    max_concurrency: configForm.media_max_concurrency,
    poll_interval_seconds: configForm.media_poll_interval_seconds,
    max_duration_seconds: configForm.media_max_duration_seconds,
    max_file_mb: configForm.media_max_file_mb,
  };
}

function formatContextWindow(value: number): string {
  if (value >= 1_000_000 && value % 1_000_000 === 0) return `${value / 1_000_000}M tokens`;
  if (value >= 1_000 && value % 1_000 === 0) return `${value / 1_000}K tokens`;
  return `${value.toLocaleString('zh-CN')} tokens`;
}

function getProviderLabel(provider: string): string {
  if (provider === 'openai_compatible') return 'OpenAI 兼容协议';
  if (provider === 'anthropic') return 'Anthropic 协议';
  if (provider === 'mock') return 'Mock 模拟模式';
  return provider;
}

function getProviderBadgeClass(provider: string): string {
  if (provider === 'openai_compatible') return 'badge-blue';
  if (provider === 'anthropic') return 'badge-amber';
  if (provider === 'mock') return 'badge-slate';
  return 'badge-blue';
}

function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text).then(() => {
    ElMessage.success('Base URL 已复制到剪贴板');
  }).catch(() => {
    ElMessage.error('复制失败');
  });
}

function cleanBaseUrl() {
  configForm.base_url = configForm.base_url.replace(/\/chat\/completions\/?$/, '').trim();
}

function applyPreset(presetType: 'deepseek' | 'openai' | 'ollama' | 'claude') {
  configForm.context_window_tokens = 1_000_000;
  configForm.supports_multimodal = false;
  configForm.capabilities = ['text_generation', 'structured_output'];
  configForm.api_mode = 'text_chat';
  configForm.adapter_config_json_text = '{}';
  configForm.media_max_concurrency = 2;
  configForm.media_poll_interval_seconds = 2;
  configForm.media_max_duration_seconds = 1800;
  configForm.media_max_file_mb = 500;
  if (presetType === 'deepseek') {
    configForm.name = 'DeepSeek V3 官方';
    configForm.provider = 'openai_compatible';
    configForm.base_url = 'https://api.deepseek.com/v1';
    configForm.model_name = 'deepseek-chat';
    configForm.timeout_seconds = 120;
  } else if (presetType === 'openai') {
    configForm.name = 'OpenAI GPT-4o 官方';
    configForm.provider = 'openai_compatible';
    configForm.base_url = 'https://api.openai.com/v1';
    configForm.model_name = 'gpt-4o';
    configForm.timeout_seconds = 90;
  } else if (presetType === 'ollama') {
    configForm.name = 'Ollama 本地服务';
    configForm.provider = 'openai_compatible';
    configForm.base_url = 'http://localhost:11434/v1';
    configForm.model_name = 'deepseek-r1:8b';
    configForm.timeout_seconds = 180;
  } else if (presetType === 'claude') {
    configForm.name = 'Claude 3.5 Sonnet 官方';
    configForm.provider = 'anthropic';
    configForm.base_url = 'https://api.anthropic.com';
    configForm.model_name = 'claude-3-5-sonnet-20241022';
    configForm.timeout_seconds = 120;
  }
}

function getGradeLabel(level: string) {
  if (level === 'primary') return '小学';
  if (level === 'junior_high') return '初中';
  if (level === 'senior_high') return '高中';
  if (level === 'higher_ed') return '大学/职业教育';
  return '未设置 (生成时指定)';
}

function getTemplateName(id: string) {
  const found = pptTemplates.value.find(t => t.id === id);
  return found ? found.name : '学术科研·成品微课';
}

function handleProviderChange(val: string) {
  if (val === 'openai_compatible' && !configForm.base_url) {
    configForm.base_url = 'https://api.openai.com/v1';
    configForm.model_name = 'gpt-4o';
  } else if (val === 'anthropic' && configForm.base_url.includes('openai')) {
    configForm.base_url = 'https://api.anthropic.com';
    configForm.model_name = 'claude-3-5-sonnet-20241022';
  } else if (val === 'mock') {
    configForm.base_url = 'mock://local';
    configForm.model_name = 'mock-model';
  }
}

async function loadSettings() {
  loading.value = true;
  fetchError.value = '';
  try {
    const [res, catalog] = await Promise.all([settingsApi.getSettings(), pptTemplatesApi.getCatalog()]);
    pptTemplates.value = catalog.templates;
    modelConfigs.value = res.configs || [];
    modelConfigStore.setConfigs(modelConfigs.value);
    activeConfigId.value = res.active_config_id || null;
    if (res.preferences) {
      preferenceForm.default_language = res.preferences.default_language || 'zh-CN';
      preferenceForm.default_grade_level = res.preferences.default_grade_level || '';
      preferenceForm.default_ppt_template = res.preferences.default_ppt_template || 'lessonforge_deck_academic';
    }
  } catch (err: any) {
    fetchError.value = err.response?.data?.detail || err.message || '获取配置信息失败';
  } finally {
    loading.value = false;
  }
}

async function handleActivate(id: string) {
  activatingConfigId.value = id;
  try {
    await settingsApi.activateModelConfig(id);
    ElMessage.success('已成功切换激活模型配置');
    await loadSettings();
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '切换配置失败');
  } finally {
    activatingConfigId.value = null;
  }
}

async function handleCardCommand(command: string, config: ModelConfigItem) {
  if (command === 'edit') {
    handleEditConfig(config);
  } else if (command === 'test') {
    handleTestCard(config);
  } else if (command === 'activate') {
    handleActivate(config.id);
  } else if (command === 'delete') {
    handleDeleteConfig(config);
  }
}

function handleOpenCreateDialog(preset?: 'deepseek' | 'openai' | 'ollama' | 'claude') {
  editingConfigId.value = null;
  currentEditingMaskedKey.value = '';
  testResult.value = null;
  if (preset) {
    applyPreset(preset);
  } else {
    configForm.name = '';
    configForm.provider = 'openai_compatible';
    configForm.base_url = 'https://api.openai.com/v1';
    configForm.model_name = 'gpt-4o';
    configForm.api_key = '';
    configForm.timeout_seconds = 90;
    configForm.context_window_tokens = 1_000_000;
    configForm.supports_multimodal = false;
    configForm.capabilities = ['text_generation', 'structured_output'];
    configForm.api_mode = 'text_chat';
    configForm.adapter_config_json_text = '{}';
    configForm.media_max_concurrency = 2;
    configForm.media_poll_interval_seconds = 2;
    configForm.media_max_duration_seconds = 1800;
    configForm.media_max_file_mb = 500;
  }
  configForm.is_active = modelConfigs.value.length === 0;
  dialogVisible.value = true;
}

function handleEditConfig(config: ModelConfigItem) {
  editingConfigId.value = config.id;
  currentEditingMaskedKey.value = config.api_key_masked;
  testResult.value = null;
  configForm.name = config.name;
  configForm.provider = config.provider;
  configForm.base_url = config.base_url;
  configForm.model_name = config.model_name;
  configForm.api_key = '';
  configForm.timeout_seconds = config.timeout_seconds;
  configForm.context_window_tokens = config.context_window_tokens;
  configForm.supports_multimodal = config.supports_multimodal;
  configForm.capabilities = [...(config.capabilities || ['text_generation', 'structured_output'])];
  configForm.api_mode = config.api_mode || 'text_chat';
  configForm.adapter_config_json_text = JSON.stringify(config.adapter_config || {}, null, 2);
  configForm.media_max_concurrency = Number(config.adapter_config?.max_concurrency || 2);
  configForm.media_poll_interval_seconds = Number(config.adapter_config?.poll_interval_seconds || 2);
  configForm.media_max_duration_seconds = Number(config.adapter_config?.max_duration_seconds || 1800);
  configForm.media_max_file_mb = Number(config.adapter_config?.max_file_mb || 500);
  configForm.is_active = config.is_active;
  dialogVisible.value = true;
}

async function handleDeleteConfig(config: ModelConfigItem) {
  try {
    await ElMessageBox.confirm(
      `确定要删除配置 "${config.name}" 吗？此操作无法撤销。`,
      '警告',
      { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'warning' }
    );
    await settingsApi.deleteModelConfig(config.id);
    ElMessage.success('配置已成功删除');
    await loadSettings();
  } catch (err: any) {
    if (err !== 'cancel') {
      ElMessage.error(err.response?.data?.detail || '删除配置失败');
    }
  }
}

async function handleTestCard(config: ModelConfigItem) {
  testingConfigId.value = config.id;
  try {
    const res = await settingsApi.testConnection({
      config_id: config.id,
      provider: config.provider,
      base_url: config.base_url,
      model_name: config.model_name,
      timeout_seconds: 15,
      test_capability: preferredTestCapability(config.capabilities),
      api_mode: config.api_mode,
      adapter_config: config.adapter_config,
    });
    if (res.success) {
      ElMessage.success({ message: `[${config.name}] ${res.message}`, duration: 4000 });
    } else {
      ElMessage.error({ message: `[${config.name}] ${res.message}`, duration: 5000 });
    }
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || err.message || '测试连接异常');
  } finally {
    testingConfigId.value = null;
  }
}

async function handleTestInDialog() {
  if (!formRef.value) return;
  const valid = await formRef.value.validate().catch(() => false);
  if (!valid) return;

  testingConnection.value = true;
  testResult.value = null;
  try {
    let formattedUrl = configForm.base_url.trim();
    if (formattedUrl && !formattedUrl.startsWith('http://') && !formattedUrl.startsWith('https://')) {
      formattedUrl = 'https://' + formattedUrl;
    }

    const res = await settingsApi.testConnection({
      config_id: editingConfigId.value || undefined,
      provider: configForm.provider,
      base_url: formattedUrl,
      model_name: configForm.model_name.trim(),
      api_key: configForm.api_key.trim(),
      timeout_seconds: 15,
      test_capability: preferredTestCapability(configForm.capabilities),
      api_mode: configForm.api_mode,
      adapter_config: adapterWithMediaLimits(JSON.parse(configForm.adapter_config_json_text || '{}')),
    });
    testResult.value = { success: res.success, message: res.message };
  } catch (err: any) {
    testResult.value = {
      success: false,
      message: err.response?.data?.detail || err.message || '测试连通性出错',
    };
  } finally {
    testingConnection.value = false;
  }
}

async function handleSubmitConfig() {
  if (!formRef.value) return;
  const valid = await formRef.value.validate().catch(() => false);
  if (!valid) return;

  submitting.value = true;
  try {
    let formattedUrl = configForm.base_url.trim();
    if (formattedUrl && !formattedUrl.startsWith('http://') && !formattedUrl.startsWith('https://')) {
      formattedUrl = 'https://' + formattedUrl;
    }

    let adapterConfig: Record<string, unknown> = {};
    try {
      adapterConfig = JSON.parse(configForm.adapter_config_json_text || '{}');
    } catch {
      ElMessage.error('自定义接口映射必须是有效 JSON');
      return;
    }
    const payload = {
      name: configForm.name.trim() || undefined,
      provider: configForm.provider,
      base_url: formattedUrl,
      model_name: configForm.model_name.trim(),
      api_key: configForm.api_key.trim() || undefined,
      timeout_seconds: configForm.timeout_seconds,
      context_window_tokens: configForm.context_window_tokens,
      supports_multimodal: configForm.capabilities.includes('vision_review'),
      capabilities: configForm.capabilities,
      api_mode: configForm.api_mode,
      adapter_config: adapterWithMediaLimits(adapterConfig),
      is_active: configForm.is_active,
    };

    if (editingConfigId.value) {
      await settingsApi.updateModelConfig(editingConfigId.value, payload);
      ElMessage.success('模型配置已成功修改');
    } else {
      await settingsApi.createModelConfig(payload);
      ElMessage.success('模型配置新建成功');
    }
    dialogVisible.value = false;
    await loadSettings();
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '保存模型配置失败');
  } finally {
    submitting.value = false;
  }
}

async function handleSavePreferences() {
  savingPreferences.value = true;
  try {
    await settingsApi.updatePreferences(preferenceForm);
    ElMessage.success('默认生成偏好已成功更新保存');
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '保存偏好设置失败');
  } finally {
    savingPreferences.value = false;
  }
}

onMounted(() => {
  loadSettings();
});
</script>

<style scoped>
/* 严格一页式 Single Page Viewport 容器 */
.single-page-layout {
  height: 100%;
  max-height: 100%;
  width: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  padding: 14px 24px 18px;
  max-width: var(--content-max-width);
  margin: 0 auto;
  overflow: hidden;
}

/* 1. 超紧凑型 Header */
.settings-header-compact {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-default);
  flex-shrink: 0;
}

.header-left-info {
  display: flex;
  flex-direction: column;
}

.header-eyebrow {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--color-primary);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
}

.header-title-row {
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.header-title {
  font-size: 20px;
  font-weight: 900;
  letter-spacing: -0.02em;
  margin: 0;
  color: var(--text-primary);
}

.header-subtitle-inline {
  color: var(--text-muted);
  font-size: 12.5px;
  font-weight: 500;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.shadow-glow {
  box-shadow: 0 4px 14px rgba(79, 70, 229, 0.25) !important;
}

/* 2. 4 维顶部指标概览栏 (双层上下布局，完全杜绝横向挤压) */
.metrics-bar {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 14px;
  flex-shrink: 0;
}

@media (max-width: 1024px) {
  .metrics-bar {
    grid-template-columns: repeat(2, 1fr);
  }
}

.metric-chip {
  background: #ffffff;
  border: 1.5px solid #e2e8f0;
  border-radius: 14px;
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 8px;
  border-left-width: 4px;
  transition: all 200ms cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.03);
  min-width: 0;
  overflow: hidden;
}

.metric-chip:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.08);
}

.metric-chip.border-indigo { border-left-color: #4f46e5; }
.metric-chip.border-blue { border-left-color: #0284c7; }
.metric-chip.border-emerald { border-left-color: #059669; }
.metric-chip.border-violet { border-left-color: #7c3aed; }

.chip-top-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.chip-label-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.metric-icon {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  font-size: 15px;
  flex-shrink: 0;
}

.metric-icon.bg-indigo { background: #eef2ff; color: #4f46e5; }
.metric-icon.bg-blue { background: #f0f9ff; color: #0284c7; }
.metric-icon.bg-emerald { background: #ecfdf5; color: #059669; }
.metric-icon.bg-violet { background: #f5f3ff; color: #7c3aed; }

.chip-label {
  font-size: 12px;
  color: #64748b;
  font-weight: 700;
  white-space: nowrap;
}

.chip-title-val {
  font-size: 14.5px;
  font-weight: 800;
  color: #0f172a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.3;
}

.chip-unit {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
}

.status-badge-wrap {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 700;
  color: #047857;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  padding: 2px 8px;
  border-radius: 999px;
  white-space: nowrap;
  flex-shrink: 0;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #cbd5e1;
}

.status-dot.green {
  background: #10b981;
  box-shadow: 0 0 6px #10b981;
}

.chip-tag {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
  white-space: nowrap;
  flex-shrink: 0;
}

.chip-tag.tag-blue { background: #e0f2fe; color: #0369a1; border: 1px solid #bae6fd; }
.chip-tag.tag-emerald { background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0; }
.chip-tag.tag-purple { background: #f5f3ff; color: #7c3aed; border: 1px solid #ddd6fe; }

/* 3. Tab 控制条 */
.tab-control-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  flex-shrink: 0;
  gap: 12px;
}

.segmented-tabs {
  display: inline-flex;
  padding: 4px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  gap: 4px;
}

.tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 18px;
  border: 0;
  background: transparent;
  border-radius: 999px;
  font-size: 13.5px;
  font-weight: 700;
  color: #475569;
  cursor: pointer;
  transition: all 180ms ease;
}

.tab-btn:hover {
  color: #0f172a;
}

.tab-btn.active {
  background: #ffffff;
  color: #4f46e5;
  box-shadow: 0 3px 12px rgba(79, 70, 229, 0.12);
}

.tab-badge {
  font-size: 11px;
  font-weight: 800;
  background: #eef2ff;
  color: #4f46e5;
  padding: 2px 8px;
  border-radius: 999px;
}

.quick-presets-strip {
  display: flex;
  align-items: center;
  gap: 6px;
}

.strip-label {
  font-size: 12.5px;
  color: #64748b;
  font-weight: 700;
}

.mini-preset-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 13px;
  border-radius: 999px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  font-size: 12px;
  font-weight: 700;
  color: #334155;
  cursor: pointer;
  transition: all 180ms ease;
}

.mini-preset-btn:hover {
  border-color: #a5b4fc;
  background: #f8fafc;
  color: #4f46e5;
  transform: translateY(-1px);
  box-shadow: 0 3px 10px rgba(79, 70, 229, 0.08);
}

.btn-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.bg-blue-500 { background: #3b82f6; }
.bg-emerald-500 { background: #10b981; }
.bg-amber-500 { background: #f59e0b; }
.bg-purple-500 { background: #8b5cf6; }

/* 4. Tab 视图主体区域 */
.tab-content-container {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.tab-pane {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  padding-right: 4px;
  padding-bottom: 12px;
}

.tab-pane::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

.tab-pane::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 999px;
}

.tab-pane::-webkit-scrollbar-thumb:hover {
  background: #94a3b8;
}

.tab-pane::-webkit-scrollbar-track {
  background: transparent;
}

/* Tab 1: 空状态与卡片 */
.empty-onboarding-card {
  padding: 18px 22px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-card);
  background: linear-gradient(180deg, #ffffff 0%, var(--surface-secondary) 100%);
  box-shadow: var(--shadow-xs);
}

.empty-header {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-light);
}

.empty-icon-glow {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-control);
  background: linear-gradient(135deg, var(--primary-500) 0%, var(--accent-violet) 100%);
  color: #ffffff;
  display: grid;
  place-items: center;
  font-size: 24px;
  flex-shrink: 0;
}

.empty-title { font-size: 16px; font-weight: 800; color: var(--text-primary); margin: 0; }
.empty-sub { font-size: 12.5px; color: var(--text-muted); margin: 2px 0 0; }

.preset-cards-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}

.preset-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-control);
  padding: 12px;
  cursor: pointer;
  transition: all var(--motion-fast);
}

.preset-card:hover {
  border-color: var(--color-primary);
  transform: translateY(-2px);
  box-shadow: var(--shadow-sm);
}

.preset-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.action-hint {
  font-size: 10.5px;
  font-weight: 800;
  color: var(--color-primary);
  opacity: 0;
}

.preset-card:hover .action-hint {
  opacity: 1;
}

.preset-badge {
  font-size: 10.5px;
  font-weight: 800;
  padding: 2px 6px;
  border-radius: 3px;
}

.badge-blue { background: #dbeafe; color: #1e40af; }
.badge-emerald { background: #d1fae5; color: #065f46; }
.badge-amber { background: #fef3c7; color: #92400e; }
.badge-purple { background: #f3e8ff; color: #6b21a8; }
.badge-slate { background: #e2e8f0; color: #334155; }

.preset-name { font-size: 13.5px; font-weight: 800; color: var(--text-primary); margin: 6px 0 2px; }
.preset-url { font-size: 11px; color: var(--text-muted); font-family: monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* Model Cards Grid */
.model-cards-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 14px;
  padding: 2px 2px 8px 2px;
}

@media (max-width: 900px) {
  .model-cards-grid {
    grid-template-columns: 1fr;
  }
}

.config-card {
  padding: 18px 20px;
  border-radius: 16px;
  border: 1.5px solid #e2e8f0;
  background: #ffffff;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.03);
  transition: all 220ms cubic-bezier(0.16, 1, 0.3, 1);
  position: relative;
  overflow: hidden;
}

.config-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
}

.config-card.active {
  border-color: #4f46e5;
  box-shadow: 0 0 0 1px #4f46e5, 0 10px 28px rgba(79, 70, 229, 0.12);
  background: linear-gradient(180deg, #f5f3ff 0%, #ffffff 100%);
}

.config-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.badge-group { display: flex; align-items: center; gap: 8px; }
.provider-badge {
  font-size: 11.5px;
  font-weight: 800;
  padding: 3px 10px;
  border-radius: 999px;
  background: #e0f2fe;
  color: #0369a1;
  border: 1px solid #bae6fd;
}
.active-tag {
  font-size: 11.5px;
  font-weight: 800;
  padding: 3px 10px;
  border-radius: 999px;
  background: #ecfdf5;
  color: #047857;
  border: 1px solid #a7f3d0;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.pulse-dot { width: 6px; height: 6px; border-radius: 50%; background: #10b981; box-shadow: 0 0 6px #10b981; }

.config-title {
  font-size: 16px;
  font-weight: 800;
  color: #0f172a;
  margin: 0 0 8px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  letter-spacing: -0.01em;
}

.url-display-box {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #475569;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  padding: 6px 10px;
  border-radius: 10px;
  margin-bottom: 12px;
}
.url-icon { flex-shrink: 0; color: #64748b; font-size: 13px; }
.url-text { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; font-weight: 500; }
.copy-btn { background: transparent; border: 0; color: #64748b; cursor: pointer; padding: 2px; border-radius: 4px; display: grid; place-items: center; transition: color 150ms ease; }
.copy-btn:hover { color: #4f46e5; }

.config-details-compact {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 10px 12px;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px 12px;
  font-size: 12.5px;
  margin-bottom: 14px;
}
.detail-item { display: flex; align-items: center; gap: 4px; min-width: 0; }
.detail-item .lbl { color: #64748b; font-weight: 600; flex-shrink: 0; }
.detail-item .val { font-weight: 700; color: #0f172a; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.detail-item .val.key-ok { color: #047857; font-weight: 700; }
.detail-item .val.key-no { color: #dc2626; font-weight: 700; }
.detail-item .text-violet { color: #7c3aed; font-weight: 800; }

.config-card-footer {
  margin-top: 4px;
  padding-top: 12px;
  border-top: 1px dashed #cbd5e1;
  display: flex;
  gap: 10px;
}

.config-card-footer :deep(.el-button) {
  border-radius: 999px !important;
  font-weight: 700 !important;
  font-size: 12.5px !important;
  flex: 1;
}

.config-card-footer :deep(.el-button--success.is-plain) {
  background: #ecfdf5 !important;
  color: #047857 !important;
  border-color: #a7f3d0 !important;
}

.config-card-footer :deep(.el-button--success.is-plain:hover) {
  background: #059669 !important;
  color: #ffffff !important;
  border-color: #059669 !important;
  box-shadow: 0 4px 12px rgba(5, 150, 105, 0.25) !important;
}

.config-card-footer :deep(.el-button--primary) {
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%) !important;
  border: 0 !important;
  color: #ffffff !important;
  box-shadow: 0 3px 10px rgba(79, 70, 229, 0.25) !important;
}

.config-card-footer :deep(.el-button--primary:hover) {
  box-shadow: 0 4px 14px rgba(79, 70, 229, 0.35) !important;
}

/* Tab 2: 偏好 Grid */
.preferences-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 18px;
  align-items: stretch;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

@media (max-width: 900px) {
  .preferences-grid {
    grid-template-columns: 1fr;
    overflow-y: auto;
  }
}

.pref-card {
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 12px;
  border: 1.5px solid #e2e8f0;
  border-radius: 16px;
  background: #ffffff;
  height: 100%;
  box-sizing: border-box;
  overflow: hidden;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.03);
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0;
  padding-bottom: 10px;
  border-bottom: 1px solid #f1f5f9;
  flex-shrink: 0;
}

.pane-card-title {
  font-size: 16px;
  font-weight: 800;
  color: #0f172a;
  margin: 0;
}

.title-sub {
  font-size: 12px;
  color: #64748b;
  font-weight: 500;
}

.pref-form {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.pref-form :deep(.el-form-item) {
  margin-bottom: 8px !important;
}

.pref-form :deep(.el-form-item__label) {
  font-size: 13px !important;
  font-weight: 700 !important;
  color: #0f172a !important;
  margin-bottom: 4px !important;
  line-height: 1.2 !important;
}

.pref-form :deep(.el-input__wrapper),
.pref-form :deep(.el-select__wrapper) {
  border-radius: 12px !important;
  background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%) !important;
  box-shadow: 0 0 0 1.5px #cbd5e1 inset, 0 2px 6px rgba(15, 23, 42, 0.03) !important;
  padding: 4px 14px !important;
  transition: all 200ms ease !important;
  height: 40px !important;
}

.pref-form :deep(.el-input__wrapper:hover),
.pref-form :deep(.el-select__wrapper:hover),
.pref-form :deep(.el-input__wrapper.is-focus),
.pref-form :deep(.el-select__wrapper.is-focused) {
  box-shadow: 0 0 0 2px #4f46e5 inset, 0 4px 16px rgba(79, 70, 229, 0.15) !important;
  background: #ffffff !important;
}

.pref-form :deep(.el-input__inner),
.pref-form :deep(.el-select__placeholder),
.pref-form :deep(.el-select__selected-item) {
  font-size: 13px !important;
  font-weight: 600 !important;
  color: #0f172a !important;
}

.form-btn-row {
  margin-top: 8px;
}

.save-pref-btn {
  font-weight: 800 !important;
  border-radius: 12px !important;
  height: 40px !important;
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%) !important;
  border: 0 !important;
}

/* 左侧卡片实时偏好规约面板 */
.preference-active-summary {
  margin-top: 8px;
  padding: 12px 14px;
  background: linear-gradient(135deg, #f8fafc 0%, #eef2ff 100%);
  border: 1px solid #c7d2fe;
  border-radius: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.summary-title-line {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 800;
  color: #4338ca;
}

.summary-chips-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}

.summary-chip-item {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.02);
}

.summary-chip-item .chip-k {
  font-size: 11px;
  color: #64748b;
  font-weight: 600;
}

.summary-chip-item .chip-v {
  font-size: 12.5px;
  color: #0f172a;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.summary-chip-item .chip-v.highlight {
  color: #4f46e5;
  font-weight: 800;
}

.summary-footer-tip {
  margin: 0;
  font-size: 11.5px;
  color: #64748b;
  line-height: 1.45;
}

/* 纵向模板列表：内嵌可滚动，充满卡片高度 */
.template-vertical-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 4px;
}

.visual-tpl-card-compact {
  border: 1.5px solid #e2e8f0;
  border-radius: 14px;
  overflow: hidden;
  cursor: pointer;
  transition: all 200ms cubic-bezier(0.16, 1, 0.3, 1);
  background: #ffffff;
  display: flex;
  align-items: center;
  padding: 12px 16px;
  gap: 14px;
  flex-shrink: 0;
}

.visual-tpl-card-compact:hover {
  border-color: #a5b4fc;
  transform: translateX(3px);
  box-shadow: 0 4px 14px rgba(79, 70, 229, 0.08);
}

.visual-tpl-card-compact.selected {
  border-color: #4f46e5;
  background: linear-gradient(135deg, rgba(79, 70, 229, 0.04) 0%, #ffffff 100%);
  box-shadow: 0 4px 16px rgba(79, 70, 229, 0.12);
}

/* Dynamic Slide Cover Thumbnail */
.slide-thumb-cover {
  width: 78px;
  height: 52px;
  border-radius: 8px;
  padding: 6px;
  box-sizing: border-box;
  flex-shrink: 0;
  box-shadow: 0 3px 10px rgba(15, 23, 42, 0.15);
  position: relative;
  overflow: hidden;
}

.slide-cover-inner {
  width: 100%;
  height: 100%;
  background: rgba(255, 255, 255, 0.2);
  backdrop-filter: blur(4px);
  border-radius: 5px;
  padding: 5px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.cover-top-tag {
  width: 14px;
  height: 3px;
  background: #ffffff;
  border-radius: 1px;
}

.cover-title-line {
  height: 4px;
  width: 80%;
  background: #ffffff;
  border-radius: 1px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
}

.cover-sub-lines {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sub-line {
  height: 2.5px;
  background: rgba(255, 255, 255, 0.85);
  border-radius: 1px;
}

.sub-line.l1 { width: 90%; }
.sub-line.l2 { width: 60%; }

.slide-info-wrap {
  flex: 1;
  min-width: 0;
}

.slide-info-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.slide-name {
  font-size: 14.5px;
  font-weight: 800;
  color: #0f172a;
}

.checked-badge-pill {
  font-size: 11.5px;
  font-weight: 800;
  color: #047857;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  padding: 2px 9px;
  border-radius: 999px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.slide-desc {
  font-size: 12px;
  color: #64748b;
  margin: 0;
  line-height: 1.45;
}

/* Tab 3: 协议 Grid */
.protocols-grid {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 16px;
}

.protocol-cards-column { display: flex; flex-direction: column; gap: 10px; }

.protocol-box {
  background: #ffffff;
  border: 1.5px solid #e2e8f0;
  border-radius: 14px;
  padding: 14px 16px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.03);
}

.protocol-box-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.protocol-icon { width: 26px; height: 26px; border-radius: 6px; display: grid; place-items: center; font-size: 14px; }
.protocol-name { font-size: 14px; font-weight: 800; color: #0f172a; }
.protocol-desc { font-size: 12.5px; color: #64748b; margin: 0 0 8px; line-height: 1.4; }
.protocol-footer { font-size: 11.5px; color: #64748b; font-family: monospace; border-top: 1px dashed #e2e8f0; padding-top: 6px; }

.runtime-status-card {
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
  color: #ffffff;
  padding: 20px;
  border-radius: 16px;
  position: relative;
  overflow: hidden;
  box-sizing: border-box;
}

.bg-watermark { position: absolute; right: -15px; bottom: -15px; font-size: 90px; opacity: 0.06; pointer-events: none; }
.runtime-card-title { font-size: 15px; font-weight: 800; color: #ffffff; margin: 0 0 14px; display: flex; align-items: center; gap: 8px; }
.ic-indigo { color: #818cf8; }

.runtime-info-list { display: flex; flex-direction: column; gap: 10px; font-size: 12.5px; }
.runtime-info-row { display: flex; justify-content: space-between; padding-bottom: 8px; border-bottom: 1px solid rgba(255, 255, 255, 0.08); }
.runtime-info-row.no-border { border-bottom: 0; padding-bottom: 0; }
.rt-label { color: #94a3b8; }
.rt-val { color: #e2e8f0; font-weight: 600; }
.text-emerald { color: #34d399; }
.text-indigo { color: #a5b4fc; }

/* ElDialog Modal Overrides */
:deep(.config-modal-dialog) {
  border-radius: 20px !important;
  overflow: hidden !important;
  box-shadow: 0 25px 50px -12px rgba(15, 23, 42, 0.25), 0 0 0 1px rgba(255, 255, 255, 0.8) inset !important;
  background: #ffffff !important;
}

:deep(.config-modal-dialog .el-dialog__header) {
  padding: 18px 24px 14px !important;
  margin-right: 0 !important;
  border-bottom: 1px solid var(--border-light) !important;
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%) !important;
}

:deep(.config-modal-dialog .el-dialog__headerbtn) {
  top: 18px !important;
  right: 20px !important;
  width: 32px !important;
  height: 32px !important;
  border-radius: 50% !important;
  transition: all var(--motion-fast) !important;
}

:deep(.config-modal-dialog .el-dialog__headerbtn:hover) {
  background: #f1f5f9 !important;
  color: var(--color-primary) !important;
}

:deep(.config-modal-dialog .el-dialog__body) {
  padding: 20px 24px !important;
  max-height: calc(75vh - 100px) !important;
  overflow-y: auto !important;
}

:deep(.config-modal-dialog .el-dialog__footer) {
  padding: 14px 24px !important;
  background: #f8fafc !important;
  border-top: 1px solid var(--border-light) !important;
}

.modal-custom-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.modal-header-icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  font-size: 20px;
  flex-shrink: 0;
  box-shadow: 0 4px 12px rgba(79, 70, 229, 0.25);
}

.modal-header-icon.bg-indigo {
  background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
  color: #ffffff;
}

.modal-header-title {
  font-size: 17px;
  font-weight: 800;
  color: var(--text-primary);
  margin: 0;
  letter-spacing: -0.01em;
}

.modal-header-sub {
  font-size: 12px;
  color: var(--text-muted);
  margin: 2px 0 0;
  font-weight: 500;
}

.preset-dialog-bar {
  background: linear-gradient(135deg, #f8fafc 0%, #eef2ff 100%);
  border: 1px solid #e0e7ff;
  border-radius: 14px;
  padding: 10px 14px;
  margin-bottom: 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.preset-bar-title {
  font-size: 12.5px;
  font-weight: 800;
  color: #334155;
  display: flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
}

.preset-bar-title .ic-indigo {
  color: #4f46e5;
  font-size: 15px;
}

.preset-bar-btns {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.preset-chip {
  padding: 4px 11px;
  border-radius: 8px;
  border: 1px solid transparent;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: all var(--motion-fast) var(--ease-out-smooth);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.preset-chip:hover {
  transform: translateY(-1.5px);
  box-shadow: 0 4px 10px rgba(15, 23, 42, 0.08);
}

.preset-chip:active {
  transform: translateY(0);
}

.preset-chip.chip-blue {
  color: #1d4ed8;
  background: #eff6ff;
  border-color: #bfdbfe;
}
.preset-chip.chip-blue:hover { background: #dbeafe; }

.preset-chip.chip-emerald {
  color: #047857;
  background: #ecfdf5;
  border-color: #a7f3d0;
}
.preset-chip.chip-emerald:hover { background: #d1fae5; }

.preset-chip.chip-amber {
  color: #b45309;
  background: #fffbeb;
  border-color: #fde68a;
}
.preset-chip.chip-amber:hover { background: #fef3c7; }

.preset-chip.chip-purple {
  color: #6d28d9;
  background: #f5f3ff;
  border-color: #ddd6fe;
}
.preset-chip.chip-purple:hover { background: #ede9fe; }

.dialog-form-row {
  display: flex;
  gap: 14px;
}

.form-col {
  flex: 1;
  min-width: 0;
}

.capability-switch-row {
  background: var(--surface-secondary);
  border: 1px solid var(--border-default);
  border-radius: 14px;
  padding: 8px 14px;
  margin-top: 6px;
}

.url-hint-row {
  font-size: 11.5px;
  color: var(--text-muted);
  margin-top: 4px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.clean-link {
  color: #d97706;
  background: #fffbeb;
  border: 1px solid #fde68a;
  padding: 1px 8px;
  border-radius: 6px;
  font-weight: 700;
  cursor: pointer;
  transition: all var(--motion-fast);
}

.clean-link:hover {
  background: #fef3c7;
  color: #b45309;
}

.key-masked-hint {
  font-size: 11.5px;
  color: #059669;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  padding: 3px 8px;
  border-radius: 6px;
  font-weight: 600;
  margin-top: 4px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.test-result-banner {
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 12.5px;
  margin-top: 10px;
  animation: fadeIn 200ms var(--ease-out-smooth);
}

.test-result-banner.bg-success {
  background: #ecfdf5;
  color: #047857;
  border: 1px solid #a7f3d0;
}

.test-result-banner.bg-danger {
  background: #fef2f2;
  color: #b91c1c;
  border: 1px solid #fecaca;
}

.banner-content {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
}

.ic-success { color: #059669; font-size: 16px; }
.ic-danger { color: #dc2626; font-size: 16px; }

.dialog-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.dialog-footer-actions {
  display: flex;
  gap: 8px;
}

.text-danger { color: var(--color-danger) !important; }
</style>
