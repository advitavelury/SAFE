export function isApprovedStaff(user, profile) {
  return Boolean(user && !user.isAnonymous && profile?.active === true
    && ["admin", "operator"].includes(profile.role));
}

export function canEditIncidents(user, profile) {
  return isApprovedStaff(user, profile) && profile.role === 'admin';
}

const accessErrors = {
  "permission-denied": "Firestore denied access to your staff profile. Contact your administrator to check the project's access rules. (permission-denied)",
  "unavailable": "Firestore is temporarily unreachable. Check your connection and retry. (unavailable)",
  "unauthenticated": "Your session could not be verified. Sign out and sign in again. (unauthenticated)",
  "failed-precondition": "Firestore could not complete the staff lookup. Contact your administrator to check the database setup. (failed-precondition)",
  "auth/network-request-failed": "Firebase could not be reached. Check your connection and retry. (auth/network-request-failed)",
};

export function staffAccessErrorMessage(errorCode) {
  return Object.hasOwn(accessErrors, errorCode) ? accessErrors[errorCode]
    : "Check your connection or contact your administrator.";
}

function safeAccessErrorCode(error) {
  return Object.hasOwn(accessErrors, error?.code) ? error.code : "unknown";
}

// A generation counter prevents a previous account's late callbacks from
// restoring access after sign-out, account switching, or component teardown.
export function watchStaffAccess({ watchAuth, watchProfile }, emit) {
  let generation = 0;
  let stopProfile;
  const stopAuth = watchAuth((user) => {
    const current = ++generation;
    stopProfile?.();
    stopProfile = undefined;
    if (!user || user.isAnonymous) {
      emit({ status: "signed-out", user: null });
      return;
    }
    emit({ status: "checking", user });
    stopProfile = watchProfile(user.uid, (profile, fromCache) => {
      if (current !== generation) return;
      if (fromCache) {
        emit({ status: "checking", user });
        return;
      }
      emit({ status: isApprovedStaff(user, profile) ? "ready" : "denied", user, profile });
    }, (error) => {
      if (current === generation) emit({ status: "error", user, errorCode: safeAccessErrorCode(error) });
    });
  }, (error) => {
    generation++;
    stopProfile?.();
    emit({ status: "error", user: null, errorCode: safeAccessErrorCode(error) });
  });
  return () => {
    generation++;
    stopProfile?.();
    stopAuth();
  };
}
