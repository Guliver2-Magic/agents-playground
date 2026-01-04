import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { CheckIcon, ChevronIcon } from "./icons";
import { useConfig, VoiceOption } from "@/hooks/useConfig";

type SettingType = "inputs" | "outputs" | "chat" | "theme_color";

type SettingValue = {
  title: string;
  type: SettingType | "separator";
  key: string;
};

const VOICE_OPTIONS: { id: VoiceOption; label: string; description: string }[] = [
  { id: "aria", label: "ARIA", description: "Default assistant" },
  { id: "c3po", label: "C-3PO", description: "Protocol droid" },
  { id: "barry", label: "Barry", description: "Male voice" },
  { id: "hannah", label: "Hannah", description: "Natural female" },
  { id: "sarah", label: "Sarah", description: "Warm female" },
  { id: "leo", label: "Leo", description: "Young male" },
];

const settingsDropdown: SettingValue[] = [
  {
    title: "Show chat",
    type: "chat",
    key: "N/A",
  },
  {
    title: "---",
    type: "separator",
    key: "separator_1",
  },
  {
    title: "Show video",
    type: "outputs",
    key: "video",
  },
  {
    title: "Show audio",
    type: "outputs",
    key: "audio",
  },

  {
    title: "---",
    type: "separator",
    key: "separator_2",
  },
  {
    title: "Enable camera",
    type: "inputs",
    key: "camera",
  },
  {
    title: "Enable mic",
    type: "inputs",
    key: "mic",
  },
  {
    title: "Allow screenshare",
    type: "inputs",
    key: "screen",
  },
];

export const SettingsDropdown = () => {
  const { config, setUserSettings } = useConfig();

  const isEnabled = (setting: SettingValue) => {
    if (setting.type === "separator" || setting.type === "theme_color")
      return false;
    if (setting.type === "chat") {
      return config.settings[setting.type];
    }

    if (setting.type === "inputs") {
      const key = setting.key as "camera" | "mic" | "screen";
      return config.settings.inputs[key];
    } else if (setting.type === "outputs") {
      const key = setting.key as "video" | "audio";
      return config.settings.outputs[key];
    }

    return false;
  };

  const toggleSetting = (setting: SettingValue) => {
    if (setting.type === "separator" || setting.type === "theme_color") return;
    const newValue = !isEnabled(setting);
    const newSettings = { ...config.settings };

    if (setting.type === "chat") {
      newSettings.chat = newValue;
    } else if (setting.type === "inputs") {
      newSettings.inputs[setting.key as "camera" | "mic" | "screen"] = newValue;
    } else if (setting.type === "outputs") {
      newSettings.outputs[setting.key as "video" | "audio"] = newValue;
    }
    setUserSettings(newSettings);
  };

  const setVoice = (voice: VoiceOption) => {
    const newSettings = { ...config.settings, voice };
    setUserSettings(newSettings);
  };

  const currentVoice = VOICE_OPTIONS.find(v => v.id === config.settings.voice) || VOICE_OPTIONS[0];

  return (
    <DropdownMenu.Root modal={false}>
      <DropdownMenu.Trigger className="group inline-flex max-h-12 items-center gap-1 rounded-md hover:bg-gray-800 bg-gray-900 border-gray-800 p-1 pr-2 text-gray-100 my-auto text-sm flex gap-1 pl-2 py-1 h-full items-center">
        Settings
        <ChevronIcon />
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          className="z-50 flex w-60 flex-col gap-0 overflow-hidden rounded text-gray-100 border border-gray-800 bg-gray-900 py-2 text-sm"
          sideOffset={5}
          collisionPadding={16}
        >
          {/* Voice Selector Submenu */}
          <DropdownMenu.Sub>
            <DropdownMenu.SubTrigger className="flex max-w-full flex-row items-center justify-between px-3 py-2 text-xs hover:bg-gray-800 cursor-pointer outline-none">
              <div className="flex items-center gap-2">
                <div className="w-4 h-4 flex items-center">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
                    <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                    <line x1="12" y1="19" x2="12" y2="23"/>
                    <line x1="8" y1="23" x2="16" y2="23"/>
                  </svg>
                </div>
                <span>Voice: {currentVoice.label}</span>
              </div>
              <ChevronIcon className="rotate-[-90deg]" />
            </DropdownMenu.SubTrigger>
            <DropdownMenu.Portal>
              <DropdownMenu.SubContent
                className="z-50 flex w-48 flex-col gap-0 overflow-hidden rounded text-gray-100 border border-gray-800 bg-gray-900 py-2 text-sm"
                sideOffset={8}
              >
                {VOICE_OPTIONS.map((voice) => (
                  <DropdownMenu.Item
                    key={voice.id}
                    onClick={() => setVoice(voice.id)}
                    className="flex max-w-full flex-row items-center gap-2 px-3 py-2 text-xs hover:bg-gray-800 cursor-pointer outline-none"
                  >
                    <div className="w-4 h-4 flex items-center">
                      {config.settings.voice === voice.id && <CheckIcon />}
                    </div>
                    <div className="flex flex-col">
                      <span className="font-medium">{voice.label}</span>
                      <span className="text-gray-500 text-[10px]">{voice.description}</span>
                    </div>
                  </DropdownMenu.Item>
                ))}
              </DropdownMenu.SubContent>
            </DropdownMenu.Portal>
          </DropdownMenu.Sub>

          <div className="border-t border-gray-800 my-2" />

          {settingsDropdown.map((setting) => {
            if (setting.type === "separator") {
              return (
                <div
                  key={setting.key}
                  className="border-t border-gray-800 my-2"
                />
              );
            }

            return (
              <DropdownMenu.Label
                key={setting.key}
                onClick={() => toggleSetting(setting)}
                className="flex max-w-full flex-row items-end gap-2 px-3 py-2 text-xs hover:bg-gray-800 cursor-pointer"
              >
                <div className="w-4 h-4 flex items-center">
                  {isEnabled(setting) && <CheckIcon />}
                </div>
                <span>{setting.title}</span>
              </DropdownMenu.Label>
            );
          })}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
};
