-- Fix: permitir tiers free/premium en licenses.tier
ALTER TABLE public.licenses DROP CONSTRAINT IF EXISTS licenses_tier_check;
ALTER TABLE public.licenses ADD CONSTRAINT licenses_tier_check CHECK (
    tier = ANY (ARRAY['free'::text, 'pro'::text, 'premium'::text, 'trial'::text, 'lifetime'::text])
);