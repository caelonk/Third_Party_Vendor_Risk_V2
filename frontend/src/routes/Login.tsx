import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useSearchParams } from "react-router-dom";
import { z } from "zod";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/auth/AuthProvider";
import { GoogleSignIn } from "@/components/GoogleSignIn";
import { ssoErrorMessage } from "@/features/sso";
import { AuthLayout } from "./AuthLayout";

const schema = z.object({
  email: z.string().email("Enter a valid email"),
  password: z.string().min(1, "Enter your password"),
});
type Form = z.infer<typeof schema>;

export function Login() {
  const { login } = useAuth();
  const [params, setParams] = useSearchParams();
  // A failed Google sign-in comes back as /login?sso_error=<code>.
  const [error, setError] = useState<string | null>(() => ssoErrorMessage(params.get("sso_error")));
  useEffect(() => {
    // Drop the code from the address bar so a reload doesn't repeat the message.
    if (params.has("sso_error")) setParams({}, { replace: true });
  }, [params, setParams]);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Form>({ resolver: zodResolver(schema) });

  const onSubmit = async (values: Form) => {
    setError(null);
    try {
      await login(values.email, values.password);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    }
  };

  return (
    <AuthLayout
      title="Sign in"
      subtitle="Welcome back. Enter your credentials to continue."
      footer={
        <>
          No account? <Link to="/register">Create one</Link>
        </>
      }
    >
      {error && (
        <div className="banner banner--error auth__error" role="alert">
          {error}
        </div>
      )}
      <GoogleSignIn />
      <form className="auth__fields" onSubmit={handleSubmit(onSubmit)} noValidate>
        <div className="field">
          <label className="field__label" htmlFor="email">
            Email
          </label>
          <input
            id="email"
            className="input"
            type="email"
            autoComplete="email"
            autoFocus
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
            autoComplete="current-password"
            aria-invalid={!!errors.password}
            {...register("password")}
          />
          {errors.password && <span className="field__error">{errors.password.message}</span>}
        </div>
        <button className="btn btn--primary btn--block" type="submit" disabled={isSubmitting}>
          {isSubmitting ? <span className="spinner" /> : "Sign in"}
        </button>
      </form>
    </AuthLayout>
  );
}
