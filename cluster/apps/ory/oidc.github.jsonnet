// What a GitHub account becomes when Kratos makes a NEW identity out of one.
// That is registration, which kratos.yaml opens to a person the access plane's
// gate admits. Signing in and linking find an identity by the account's
// numeric id and never evaluate this file, so nothing written here can fail
// either of them. A registration this file fails ends on the error page, and
// the gate is never asked.
//
// `traits.email` IS REQUIRED BY THE IDENTITY SCHEMA, SO EVERY ACCOUNT IS GIVEN
// ONE. An identity without it is not stored: Kratos sends the person to the
// registration page to supply one, and kratos.yaml names a page there that is
// not Kratos's form. Where GitHub says it verified the address it lists, that
// address. Otherwise one under GitHub's no-reply domain, made of the account's
// id and login, the two claims no account lacks. Nothing here sends mail to
// either. `email_verified` is absent rather than false, and `email` is absent
// for an account that lists none, so each is looked for before it is read.
//
// THAT TRAIT IS NOT GITHUB'S WORD, AND NOTHING HERE MAKES IT SO. A person may
// post `traits.email` with the sign-in that registers them, and what is posted
// replaces what this file maps; and an identity may change the trait on the
// settings page afterwards. It is an address the person gave.
//
// `metadata_admin` IS WHAT NEITHER REPLACES: it cannot be posted, and the
// settings page does not write it. `github_login` and `github_id` are the keys
// the access plane writes on an identity it makes for an invitation
// (`src/adapters/kratos/identities.ts` in kasofsk/chuggy), both as text, and
// the login is what the plane reads a person's handle from. It is the
// account's login when the identity was made; the id is what Kratos finds the
// identity by. `github_email` is the address GitHub said it had verified at
// that moment, and is absent where GitHub said no such thing.
//
// tests/kratos-github.py evaluates this file against a verified address, an
// unverified one and none, and compares the whole of what each maps to.
local claims = std.extVar('claims');
local verified =
  std.objectHas(claims, 'email')
  && std.objectHas(claims, 'email_verified')
  && claims.email_verified == true;
{
  identity: {
    traits: {
      email:
        if verified
        then claims.email
        else claims.sub + '+' + claims.nickname + '@users.noreply.github.com',
    },
    metadata_admin: {
      github_login: claims.nickname,
      github_id: claims.sub,
      [if verified then 'github_email']: claims.email,
    },
  },
}
