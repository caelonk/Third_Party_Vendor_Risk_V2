import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";
import type { VendorInput } from "@/features/vendors";
import type { Vendor } from "@/lib/types";

const schema = z.object({
  name: z.string().trim().min(1, "Required").max(200),
  cpe_prefix: z.string().trim().max(255).optional().or(z.literal("")),
  annual_contract_value: z
    .union([z.coerce.number().min(0), z.literal("")])
    .optional(),
  data_sensitivity: z.enum(["", "public", "internal", "confidential", "regulated"]).optional(),
  business_criticality: z.enum(["", "low", "medium", "high"]).optional(),
  contract_renewal_date: z.string().optional().or(z.literal("")),
});
type Form = z.infer<typeof schema>;

function toInput(v: Form): VendorInput {
  return {
    name: v.name.trim(),
    cpe_prefix: v.cpe_prefix?.trim() || null,
    annual_contract_value:
      v.annual_contract_value === "" || v.annual_contract_value == null
        ? null
        : Number(v.annual_contract_value),
    data_sensitivity: v.data_sensitivity || null,
    business_criticality: v.business_criticality || null,
    contract_renewal_date: v.contract_renewal_date || null,
  };
}

export function VendorForm({
  vendor,
  submitting,
  error,
  onSubmit,
  submitLabel = "Add vendor",
}: {
  vendor?: Vendor;
  submitting: boolean;
  error?: string | null;
  onSubmit: (input: VendorInput) => void;
  submitLabel?: string;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Form>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: vendor?.name ?? "",
      cpe_prefix: vendor?.cpe_prefix ?? "",
      annual_contract_value: (vendor?.annual_contract_value ?? "") as number | "",
      data_sensitivity: (vendor?.data_sensitivity ?? "") as Form["data_sensitivity"],
      business_criticality: (vendor?.business_criticality ?? "") as Form["business_criticality"],
      contract_renewal_date: vendor?.contract_renewal_date ?? "",
    },
  });

  return (
    <form className="auth__fields" onSubmit={handleSubmit((v) => onSubmit(toInput(v)))} noValidate>
      {error && <div className="banner banner--error">{error}</div>}
      <div className="field">
        <label className="field__label">Vendor name</label>
        <input className="input" autoFocus aria-invalid={!!errors.name} {...register("name")} />
        {errors.name && <span className="field__error">{errors.name.message}</span>}
      </div>
      <div className="field">
        <label className="field__label">
          CPE prefix <span className="subtle">(for syncing CVEs)</span>
        </label>
        <input
          className="input mono"
          placeholder="cpe:2.3:a:fortinet"
          {...register("cpe_prefix")}
        />
        <span className="field__hint">
          NVD vendor prefix. A vendor can be added now and mapped later.
        </span>
      </div>
      <div className="row" style={{ gap: "var(--space-3)", alignItems: "flex-start" }}>
        <div className="field" style={{ flex: 1 }}>
          <label className="field__label">Data sensitivity</label>
          <select className="select" {...register("data_sensitivity")}>
            <option value="">—</option>
            <option value="public">Public</option>
            <option value="internal">Internal</option>
            <option value="confidential">Confidential</option>
            <option value="regulated">Regulated</option>
          </select>
        </div>
        <div className="field" style={{ flex: 1 }}>
          <label className="field__label">Criticality</label>
          <select className="select" {...register("business_criticality")}>
            <option value="">—</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>
        </div>
      </div>
      <div className="row" style={{ gap: "var(--space-3)", alignItems: "flex-start" }}>
        <div className="field" style={{ flex: 1 }}>
          <label className="field__label">Annual contract value</label>
          <input
            className="input mono"
            type="number"
            min={0}
            placeholder="0"
            {...register("annual_contract_value")}
          />
        </div>
        <div className="field" style={{ flex: 1 }}>
          <label className="field__label">Renewal date</label>
          <input className="input" type="date" {...register("contract_renewal_date")} />
        </div>
      </div>
      <button className="btn btn--primary btn--block" type="submit" disabled={submitting}>
        {submitting ? <span className="spinner" /> : submitLabel}
      </button>
    </form>
  );
}
