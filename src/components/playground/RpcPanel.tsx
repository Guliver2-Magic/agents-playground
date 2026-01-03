import { ConfigurationPanelItem } from "@/components/config/ConfigurationPanelItem";
import { useState } from "react";
import { LoadingSVG } from "@/components/button/LoadingSVG";
import { Button } from "@/components/button/Button";

interface RpcPanelProps {
  config: any;
  rpcMethod: string;
  rpcPayload: string;
  setRpcMethod: (method: string) => void;
  setRpcPayload: (payload: string) => void;
  handleRpcCall: () => Promise<any>;
}

// Define our 10 function tools
const FUNCTION_TOOLS = [
  {
    name: "get_weather",
    label: "🌤️ Weather",
    description: "Get weather for a location",
    fields: [
      { name: "location", label: "Location", type: "text", placeholder: "Montreal", required: true },
      { name: "units", label: "Units", type: "select", options: ["metric", "imperial"], default: "metric" },
    ],
  },
  {
    name: "find_restaurant",
    label: "🍕 Restaurant",
    description: "Find restaurants by cuisine",
    fields: [
      { name: "query", label: "Query", type: "text", placeholder: "Italian restaurant", required: true },
      { name: "location", label: "Location", type: "text", placeholder: "Montreal" },
    ],
  },
  {
    name: "get_news",
    label: "📰 News",
    description: "Get latest headlines",
    fields: [
      { name: "topic", label: "Topic", type: "text", placeholder: "technology" },
      { name: "count", label: "Count", type: "number", default: "5" },
    ],
  },
  {
    name: "search_calendar",
    label: "📅 Calendar",
    description: "Search calendar events",
    fields: [
      { name: "query", label: "Query", type: "text", placeholder: "meeting tomorrow", required: true },
      { name: "timeframe", label: "Timeframe", type: "select", options: ["today", "week", "month"], default: "week" },
    ],
  },
  {
    name: "control_home",
    label: "🏠 Home",
    description: "Control home automation",
    fields: [
      { name: "action", label: "Action", type: "text", placeholder: "turn_on", required: true },
      { name: "target", label: "Target", type: "text", placeholder: "bedroom lights", required: true },
      { name: "value", label: "Value", type: "text", placeholder: "50" },
    ],
  },
  {
    name: "make_phone_call",
    label: "📞 Phone",
    description: "Make a phone call",
    fields: [
      { name: "contact", label: "Contact", type: "text", placeholder: "Mom", required: true },
      { name: "number", label: "Number", type: "text", placeholder: "+15145551234" },
    ],
  },
  {
    name: "control_music",
    label: "🎵 Music",
    description: "Control music playback",
    fields: [
      { name: "action", label: "Action", type: "select", options: ["play", "pause", "next", "previous", "volume"], required: true },
      { name: "query", label: "Query", type: "text", placeholder: "Beatles" },
      { name: "volume", label: "Volume", type: "number", placeholder: "50" },
    ],
  },
  {
    name: "ask_about_buddy",
    label: "🐕 Buddy",
    description: "Ask about Buddy the dog",
    fields: [
      { name: "question", label: "Question", type: "text", placeholder: "Where is Buddy?", required: true },
    ],
  },
  {
    name: "get_expert_advice",
    label: "🎾 Expert",
    description: "Get expert advice",
    fields: [
      { name: "domain", label: "Domain", type: "select", options: ["tennis", "watchmaking", "vfx"], required: true },
      { name: "question", label: "Question", type: "text", placeholder: "How do I improve my serve?", required: true },
    ],
  },
  {
    name: "order_delivery",
    label: "🚚 Delivery",
    description: "Order food delivery",
    fields: [
      { name: "restaurant", label: "Restaurant", type: "text", placeholder: "Pizza Place", required: true },
      { name: "items", label: "Items (comma-separated)", type: "text", placeholder: "Large pepperoni, Garlic bread", required: true },
      { name: "address", label: "Address", type: "text", placeholder: "123 Main St" },
    ],
  },
];

export function RpcPanel({
  config,
  rpcMethod,
  rpcPayload,
  setRpcMethod,
  setRpcPayload,
  handleRpcCall,
}: RpcPanelProps) {
  const [rpcResult, setRpcResult] = useState<{
    success: boolean;
    data: any;
  } | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedTool, setSelectedTool] = useState<string>("");
  const [formValues, setFormValues] = useState<Record<string, string>>({});

  const handleToolSelect = (toolName: string) => {
    setSelectedTool(toolName);
    setRpcMethod(toolName);
    setFormValues({});
    setRpcResult(null);
  };

  const handleFieldChange = (fieldName: string, value: string) => {
    setFormValues((prev) => ({ ...prev, [fieldName]: value }));
  };

  const handleCall = async () => {
    setIsLoading(true);
    setRpcResult(null);

    // Build payload from form values
    const tool = FUNCTION_TOOLS.find((t) => t.name === selectedTool);
    const payload: Record<string, any> = {};

    if (tool) {
      tool.fields.forEach((field: any) => {
        const value = formValues[field.name] || field.default || "";
        if (value) {
          // Handle special cases
          if (field.name === "items") {
            // Split comma-separated items into array
            payload[field.name] = value.split(",").map((item: string) => item.trim());
          } else if (field.type === "number") {
            payload[field.name] = parseInt(value, 10);
          } else {
            payload[field.name] = value;
          }
        }
      });
    }

    setRpcPayload(JSON.stringify(payload));

    try {
      const result = await handleRpcCall();
      setRpcResult({ success: true, data: result });
    } catch (error) {
      setRpcResult({
        success: false,
        data: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setIsLoading(false);
    }
  };

  const selectedToolData = FUNCTION_TOOLS.find((t) => t.name === selectedTool);

  return (
    <ConfigurationPanelItem
      title="Function Tools"
      collapsible={true}
      defaultCollapsed={false}
    >
      <div className="flex flex-col gap-3">
        {/* Tool selector grid */}
        <div className="grid grid-cols-2 gap-2">
          {FUNCTION_TOOLS.map((tool) => (
            <button
              key={tool.name}
              onClick={() => handleToolSelect(tool.name)}
              className={`text-xs px-3 py-2 rounded border transition-colors ${
                selectedTool === tool.name
                  ? "border-" + config.settings.theme_color + "-500 bg-" + config.settings.theme_color + "-500/10 text-white"
                  : "border-gray-800 text-gray-400 hover:border-gray-700 hover:text-gray-300"
              }`}
            >
              {tool.label}
            </button>
          ))}
        </div>

        {/* Tool form */}
        {selectedToolData && (
          <div className="flex flex-col gap-2 mt-2 pt-2 border-t border-gray-800">
            <div className="text-xs text-gray-400">{selectedToolData.description}</div>

            {selectedToolData.fields.map((field: any) => (
              <div key={field.name} className="flex flex-col gap-1">
                <label className="text-xs text-gray-500">
                  {field.label}
                  {field.required && <span className="text-red-500 ml-1">*</span>}
                </label>

                {field.type === "select" ? (
                  <select
                    value={formValues[field.name] || field.default || ""}
                    onChange={(e) => handleFieldChange(field.name, e.target.value)}
                    className="w-full text-white text-sm bg-gray-900 border border-gray-800 rounded px-2 py-1"
                  >
                    {field.options?.map((option: string) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type={field.type || "text"}
                    value={formValues[field.name] || ""}
                    onChange={(e) => handleFieldChange(field.name, e.target.value)}
                    placeholder={field.placeholder}
                    className="w-full text-white text-sm bg-transparent border border-gray-800 rounded px-2 py-1"
                  />
                )}
              </div>
            ))}

            <Button
              accentColor={config.settings.theme_color}
              onClick={handleCall}
              disabled={isLoading}
              className="mt-2 text-xs flex items-center justify-center gap-2"
            >
              {isLoading ? (
                <>
                  <LoadingSVG diameter={12} strokeWidth={2} />
                  Calling {selectedToolData.label}...
                </>
              ) : (
                `Call ${selectedToolData.label}`
              )}
            </Button>
          </div>
        )}

        {/* Result display */}
        {rpcResult && (
          <>
            <div className="text-xs text-gray-500 mt-2">
              {rpcResult.success ? "✓ Result" : "✗ Error"}
            </div>
            <div
              className={`w-full text-xs bg-transparent border rounded px-2 py-2 max-h-48 overflow-y-auto ${
                rpcResult.success
                  ? "border-green-500 text-green-400"
                  : "border-red-500 text-red-400"
              }`}
            >
              <pre className="whitespace-pre-wrap">
                {typeof rpcResult.data === "object"
                  ? JSON.stringify(rpcResult.data, null, 2)
                  : String(rpcResult.data)}
              </pre>
            </div>
          </>
        )}
      </div>
    </ConfigurationPanelItem>
  );
}
