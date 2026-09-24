import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
import { z } from "zod";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/auth/AuthProvider";
import { GoogleSignIn } from "@/components/GoogleSignIn";
import { AuthLayout } from "./AuthLayout";

const schema = z.object({
  name: z.string().trim().max(200).optional(),
  email: z.string().email("Enter a valid email"),
  password: z.string().min(8, "At least 8 characters"),
  org_name: z.string().trim().max(200).optional(),
});
type Form = z.infer<typeof schema>;

export function Register() {
  const { register: signup } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Form>({ resolver: zodResolver(schema) });

  const onSubmit = async (values: Form) => {
    setError(null);
    try {
      await signup({
        email: values.email,
        password: values.password,
        name: values.name || undefined,
        org_name: values.org_name || undefined,
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    }
  };

  return (
    <AuthLayout
      title="Create your account"
      subtitle="Start monitoring your vendors in minutes."
      footer={
        <>
          Already have an account? <Link to="/login">Sign in</Link>
        </>
      }
    >
      <GoogleSignIn mode="signup" />
      <form className="auth__fields" onSubmit={handleSubmit(onSubmit)} noValidate>
        {error && <div className="banner banner--error">{error}</div>}
        <div className="field">
          <label className="field__label" htmlFor="name">
            Name <span className="subtle">(optional)</span>
          </label>
          <input id="name" className="input" autoComplete="name" {...register("name")} />
        </div>
        <div className="field">
          <label className="field__label" htmlFor="email">
            Work email
          </label>
          <input
            id="email"
            className="input"
            type="email"
            autoComplete="email"
            aria-invalid={!!errors.email}
            {...register("email")}
          />
          {errors.email && <span className="field__error">{errors.email.message}</span>}
        </div>
        <div className="field">
          <label className="field__label" htmlFor="password">
            Password
          </label>
          <input
            id="password"
            className="input"
            type="password"
            autoComplete="new-password"
            aria-invalid={!!errors.password}
            {...register("password")}
          />
          {errors.password ? (
            <span className="field__error">{errors.password.message}</span>
          ) : (
            <span className="field__hint">At least 8 characters.</span>
          )}
        </div>
        <div className="field">
          <label className="field__label" htmlFor="org_name">
            Organization <span className="subtle">(optional)</span>
          </label>
          <input
            id="org_name"
            className="input"
            placeholder="Defaults to your personal workspace"
            {...register("org_name")}
          />
        </div>
        <button className="btn btn--primary btn--block" type="submit" disabled={isSubmitting}>
          {isSubmitting ? <span className="spinner" /> : "Create account"}
        </button>
      </form>
    </AuthLayout>
  );
}
